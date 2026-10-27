"""Slice D: the recall hint's decisions, the pending-extraction reminder, the
settings, and that both hooks fail open."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT
import hint
import paths
import pending

CLI = ROOT / "lib" / "synapse" / "cli.py"


def run_cli(args, home, stdin=""):
    env = {**os.environ, "SYNAPSE_HOME": str(home)}
    return subprocess.run([sys.executable, str(CLI), *args], input=stdin.encode(),
                          capture_output=True, env=env)


def hit(path, score, snippet="text"):
    return {"stored_path": path, "source_path": path, "score": score, "snippet": snippet,
            "breadcrumb": path, "project": "App", "source_type": "decision"}


class HintLogicTests(unittest.TestCase):
    def test_short_prompts_and_slash_commands_get_no_hint(self):
        self.assertFalse(hint.wants_hint("yes go ahead"))
        self.assertFalse(hint.wants_hint("/synapse:recall cloudkit sharing sync"))
        self.assertTrue(hint.wants_hint("how did we handle cloudkit sharing"))

    def test_harness_events_get_no_hint(self):
        self.assertFalse(hint.wants_hint("<task-notification>\n<task-id>b1</task-id>\n<summary>CI run finished</summary>"))
        self.assertFalse(hint.wants_hint("<system-reminder>\nBackground command completed (exit code 0)"))
        self.assertTrue(hint.wants_hint("<div class=x> why does this div overflow on mobile"))
        self.assertTrue(hint.wants_hint("<pasted_content id=1> stack trace from the sync crash"))

    def test_threshold_session_memory_duplicates_and_cap(self):
        results = [hit("a", 0.9, "x"), hit("b", 0.8, "x"), hit("c", 0.75, "y"),
                   hit("d", 0.72, "z"), hit("e", 0.71, "w"), hit("f", 0.5, "v")]
        picked = hint.select(results, 0.7, 3, seen={"c"})
        self.assertEqual([h["stored_path"] for h in picked], ["a", "d", "e"])

    def test_render_marks_hints_as_navigation(self):
        text = hint.render([hit("archive/App/PLAN_1.md", 0.8, "We chose X because Y")])
        self.assertIn("not instructions", text.splitlines()[0])
        self.assertIn("archive/App/PLAN_1.md", text)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["SYNAPSE_HOME"] = str(self.tmp)

    def test_defaults_and_overrides(self):
        self.assertEqual(paths.settings(), {"recall_auto": True, "min_score": paths.DEFAULT_MIN_SCORE,
                                            "max_hits": 3, "extract_remind": True})
        (self.tmp / "config.toml").write_text("[recall]\nauto = false\nmin_score = 0.8\n[extract]\nremind = false\n")
        s = paths.settings()
        self.assertEqual((s["recall_auto"], s["min_score"], s["extract_remind"]), (False, 0.8, False))

    def test_wrong_types_are_errors_not_guesses(self):
        cfg = self.tmp / "config.toml"
        for text in ('[recall]\nauto = "false"\n', '[recall]\nmin_score = "high"\n', "[recall]\nmin_score = 1.5\n",
                     "[recall]\nmax_hits = -1\n", "[recall]\nmax_hits = true\n", 'recall = "off"\n',
                     "[extract]\nremind = 1\n"):
            cfg.write_text(text)
            with self.assertRaises(SystemExit, msg=text):
                paths.settings()
        cfg.write_text("[recall]\nmin_score = 1\nmax_hits = 0\n")
        self.assertEqual((paths.settings()["min_score"], paths.settings()["max_hits"]), (1.0, 0))

    def test_eval_home_applies_only_without_synapse_home(self):
        os.environ["EVAL_SYNAPSE_HOME"] = str(self.tmp / "eval")
        try:
            self.assertEqual(paths.home(), self.tmp)
            del os.environ["SYNAPSE_HOME"]
            self.assertEqual(paths.home(), self.tmp / "eval")
        finally:
            os.environ.pop("EVAL_SYNAPSE_HOME", None)
            os.environ["SYNAPSE_HOME"] = str(self.tmp)


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        arch = self.home / "stores" / "main" / "archive" / "demo"
        (arch / ".processed").mkdir(parents=True)
        for sid in ("2026-10-20-0900", "2026-10-21-1000"):
            (arch / f"PLAN_{sid}.md").write_text("x")
        (arch / ".processed" / "2026-10-20-0900.json").write_text("{}")
        self.project = Path(tempfile.mkdtemp()) / "demo"
        self.project.mkdir()

    def hook(self, source):
        return run_cli(["pending", "--hook"], self.home,
                       json.dumps({"source": source, "cwd": str(self.project)}))

    def test_reminds_on_startup_only(self):
        out = self.hook("startup")
        self.assertEqual(out.returncode, 0)
        ctx = json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1 archived session", ctx)
        self.assertIn("2026-10-21-1000", ctx)
        self.assertEqual(self.hook("resume").stdout, b"")
        self.assertEqual(self.hook("compact").stdout, b"")

    def test_switch_off_and_reminder_text(self):
        (self.home / "config.toml").write_text("[extract]\nremind = false\n")
        self.assertEqual(self.hook("startup").stdout, b"")
        self.assertIn("2 archived sessions", pending.reminder("demo", ["a", "b"]))


class FailOpenTests(unittest.TestCase):
    def test_hooks_stay_silent_without_a_store_or_with_bad_input(self):
        home = Path(tempfile.mkdtemp())
        for args, stdin in ((["recall-hint"], json.dumps({"prompt": "how did we handle cloudkit sharing sync", "cwd": "/"})),
                            (["recall-hint"], "not json"),
                            (["pending", "--hook"], "not json")):
            out = run_cli(args, home, stdin)
            self.assertEqual((out.returncode, out.stdout), (0, b""), args)

    def test_hooks_stay_silent_on_a_broken_config(self):
        for text in ("this is [not toml", '[recall]\nmin_score = "high"\n'):
            home = Path(tempfile.mkdtemp())
            (home / "config.toml").write_text(text)
            out = run_cli(["recall-hint"], home, json.dumps({"prompt": "how did we handle cloudkit sharing", "cwd": "/"}))
            self.assertEqual((out.returncode, out.stdout), (0, b""), text)

    @unittest.skipIf(sys.platform == "win32", "plants a POSIX venv interpreter")
    def test_hint_stays_silent_when_the_venv_interpreter_cannot_start(self):
        home = Path(tempfile.mkdtemp())
        py = home / "venv" / "bin" / "python"
        py.parent.mkdir(parents=True)
        py.write_text("#!/bin/sh\necho 'Fatal Python error: simulated' >&2\nexit 1\n")
        py.chmod(0o755)
        env = {**os.environ, "SYNAPSE_HOME": str(home), "SYNAPSE_OPTIONAL": "1"}
        env.pop("SYNAPSE_VENV_REEXEC", None)
        # -S hides site-packages, so sqlite_vec is missing and extract re-execs into the venv.
        out = subprocess.run([sys.executable, "-S", str(CLI), "recall-hint"], capture_output=True, env=env,
                             input=json.dumps({"prompt": "how did we handle cloudkit sharing", "cwd": "/"}).encode())
        self.assertEqual((out.returncode, out.stdout, out.stderr), (0, b"", b""))

    @unittest.skipUnless(shutil.which("bash") and sys.platform != "win32", "needs POSIX bash")
    def test_launcher_without_python_is_silent_only_when_optional(self):
        empty = tempfile.mkdtemp()
        cmd = [shutil.which("bash"), str(ROOT / "lib" / "py.sh"), str(CLI), "recall-hint"]
        quiet = subprocess.run(cmd, capture_output=True, env={"PATH": empty, "SYNAPSE_OPTIONAL": "1"})
        self.assertEqual((quiet.returncode, quiet.stdout, quiet.stderr), (0, b"", b""))
        loud = subprocess.run(cmd, capture_output=True, env={"PATH": empty})
        self.assertEqual(loud.returncode, 1)
        self.assertIn(b"no Python", loud.stderr)


if __name__ == "__main__":
    unittest.main()
