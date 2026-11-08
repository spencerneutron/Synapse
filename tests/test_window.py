"""The window the nudge and the gate measure against, from Claude Code's auto-compact point."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolates SYNAPSE_HOME and CLAUDE_CONFIG_DIR, sets sys.path)
from test_continuation import model_entry, write
from test_nudge import run

import autocompact
import continuation
import doctor
import paths
import setup_cmd

OPUS = "claude-opus-5-5"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.cfg = self.dir / "claude"
        self.cfg.mkdir()
        self.project = self.dir / "project"
        (self.project / ".claude").mkdir(parents=True)
        env = {k: v for k, v in os.environ.items() if k != autocompact.ENV}
        env.update(SYNAPSE_HOME=str(self.home), CLAUDE_CONFIG_DIR=str(self.cfg))
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(autocompact, "MANAGED_SETTINGS", {})
        p.start()
        self.addCleanup(p.stop)
        cwd = os.getcwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, cwd)

    def user(self, data):
        (self.cfg / "settings.json").write_text(json.dumps(data), "utf-8")

    def window(self, model=OPUS, observed=None, sid="s1"):
        return continuation.window_for(paths, sid, {"model": model}, observed)


class WindowFor(Base):
    def test_model_settings_window(self):
        # the maintainer's shape: per-model 300000 -> compaction near 267000
        self.user({"model": "opus[1m]", "modelSettings": {
            OPUS: {"effortLevel": "xhigh", "autoCompactWindow": 300000},
            "claude-fable-5-1": {"autoCompactWindow": 300000}}})
        window, source = self.window()
        self.assertEqual(window, 267000)
        self.assertEqual(source, "from the auto-compact window 300k")
        self.assertAlmostEqual(window * continuation.LOW, 160200)
        self.assertAlmostEqual(window * continuation.HIGH, 240300)
        self.assertEqual(self.window("claude-fable-5-1")[0], 267000)

    def test_key_matching_is_tolerant(self):
        for key in (OPUS + "[1m]", "Claude-Opus-5-5", "opus", "OPUS[1m]"):
            with self.subTest(key=key):
                self.user({"modelSettings": {key: {"autoCompactWindow": 300000}}})
                self.assertEqual(self.window()[0], 267000)
                self.assertEqual(self.window(OPUS + "[1m]")[0], 267000)
        self.user({"modelSettings": {"claude-haiku-4-5": {"autoCompactWindow": 150000}}})
        self.assertEqual(self.window("claude-haiku-4-5-20251001")[0], 117000)

    def test_other_models_key_does_not_apply(self):
        self.user({"modelSettings": {"claude-fable-5-1": {"autoCompactWindow": 300000}}})
        self.assertEqual(self.window(), (300000, "from the model"))

    def test_top_level_and_per_model(self):
        self.user({"autoCompactWindow": 400000, "modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        self.assertEqual(self.window()[0], 267000)
        self.assertEqual(self.window("claude-fable-5-1")[0], 367000)

    def test_project_layer_overrides_user(self):
        self.user({"autoCompactWindow": 400000})
        (self.project / ".claude" / "settings.local.json").write_text('{"autoCompactWindow": 250000}')
        self.assertEqual(self.window()[0], 217000)

    def test_env_var_wins(self):
        self.user({"modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        with mock.patch.dict(os.environ, {autocompact.ENV: "500000"}):
            self.assertEqual(self.window(), (467000, "from the auto-compact window 500k"))
        with mock.patch.dict(os.environ, {autocompact.ENV: "200k"}):
            self.assertEqual(self.window()[0], 167000)

    def test_env_block_in_settings(self):
        self.user({"autoCompactWindow": 400000, "env": {autocompact.ENV: "300000"}})
        self.assertEqual(self.window()[0], 267000)

    def test_nothing_set_keeps_defaults(self):
        self.assertEqual(self.window(), (300000, "from the model"))
        self.assertEqual(self.window("claude-haiku-4-5"), (150000, "from the model"))
        self.user({"theme": "dark", "modelSettings": {OPUS: {"effortLevel": "high"}}})
        self.assertEqual(self.window(), (300000, "from the model"))

    def test_capped_at_model_window_and_clamped(self):
        self.user({"autoCompactWindow": 300000})
        self.assertEqual(self.window("claude-haiku-4-5")[0], 167000)   # a 200k model
        self.user({"autoCompactWindow": 50000})
        self.assertEqual(self.window()[0], 67000)                      # clamped to 100k
        self.user({"autoCompactWindow": 5000000})
        self.assertEqual(self.window()[0], 967000)                     # clamped to 1M

    def test_bad_values_ignored(self):
        for bad in ("x", "1.5k", True, -1, 0, None, [300000]):
            with self.subTest(bad=bad):
                self.user({"autoCompactWindow": bad})
                self.assertEqual(self.window(), (300000, "from the model"))
        (self.cfg / "settings.json").write_text("{not json")
        self.assertEqual(self.window(), (300000, "from the model"))

    def test_explicit_config_wins(self):
        self.user({"modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        (self.home / "config.toml").write_text("[nudge]\ncontext_window = 100000\n")
        self.assertEqual(self.window(), (100000, "from your config"))

    def test_observed_compaction_is_a_lower_bound(self):
        self.user({"modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        self.assertEqual(self.window(observed=250000), (250000, "from an earlier auto-compaction"))
        self.assertEqual(self.window(observed=280000, sid="s2"), (267000, "from the auto-compact window 300k"))
        self.assertEqual(self.window(sid="s1"), (250000, "from an earlier auto-compaction"))  # kept in state


class Hooks(Base):
    """End to end: the hook processes see the settings through CLAUDE_CONFIG_DIR."""

    def setUp(self):
        super().setUp()
        self.user({"modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        self.tr = self.dir / "t.jsonl"

    def nudge(self, ctx, sid):
        write(self.tr, [model_entry(ctx, OPUS)])
        r = run({"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                 "tool_input": {}, "transcript_path": str(self.tr), "cwd": str(self.project)}, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode().strip()
        return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else None

    def test_nudge_reports_derived_window(self):
        self.assertIsNone(self.nudge(160000, "a"))
        line = self.nudge(160200, "b")
        self.assertIn("window 267k, from the auto-compact window 300k", line)

    def test_stop_gate_at_ninety_percent(self):
        import test_gate
        # no .claude-work here, so only the 90% ask can block: it fires at 240300, not below
        def stop(ctx, sid):
            write(self.tr, [model_entry(ctx, OPUS)])
            r = test_gate.run_gate({"session_id": sid, "hook_event_name": "Stop", "cwd": str(self.project),
                                    "transcript_path": str(self.tr), "stop_hook_active": False},
                                   self.home, cwd=str(self.project))
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout.decode()) if r.stdout.strip() else None
        self.assertIsNone(stop(240000, "g1"))
        out = stop(240300, "g2")
        self.assertEqual(out.get("decision"), "block", out)
        self.assertIn("about 240k tokens", out["reason"])


class Reports(Base):
    def test_doctor_line_shows_marks(self):
        self.user({"modelSettings": {OPUS: {"autoCompactWindow": 300000}}})
        rep = doctor.Report()
        with mock.patch.object(doctor, "MANAGED_SETTINGS", {}):
            doctor.check_settings(rep, self.project)
        found = [i for i in rep.items if i["check"] == "autocompact-window"]
        self.assertEqual(len(found), 1, rep.items)
        self.assertIn("300000: compacts near 267k; Synapse's deny gate 134k, 60% 160k, 90% 240k",
                      found[0]["detail"])

    def test_setup_prints_marks(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = setup_cmd.main(["--autocompact", "300k"])
        self.assertEqual(code, 0)
        self.assertIn("compacts near 267k; Synapse's deny gate 134k, 60% 160k, 90% 240k", out.getvalue())


if __name__ == "__main__":
    unittest.main()
