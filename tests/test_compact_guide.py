import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from helpers import ROOT

import doctor
from test_hooks import BASH

PY_SH = ROOT / "lib" / "py.sh"
CLI = ROOT / "lib" / "synapse" / "cli.py"


def run(stdin, **env):
    data = stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode()
    e = dict(os.environ, **env)
    cmd = [BASH, str(PY_SH), str(CLI), "compact-guide", "--hook"] if BASH else \
        [sys.executable, str(CLI), "compact-guide", "--hook"]
    e["SYNAPSE_OPTIONAL"] = "1"
    return subprocess.run(cmd, input=data, capture_output=True, env=e)


class CompactGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / ".claude-work" / "current"

    def out(self, stdin, **kw):
        r = run(stdin, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode()
        self.assertFalse(text.startswith("{"))
        self.assertLess(len(text), 10000)
        return text

    def hook(self, **extra):
        return {"cwd": str(self.root), "trigger": "manual", "custom_instructions": None, **extra}

    def test_no_planning_files(self):
        text = self.out(self.hook())
        self.assertIn("Worth keeping", text)
        self.assertNotIn("PLAN.md", text)
        self.assertNotIn("take precedence", text)
        self.assertLess(len(text), 3000)

    def test_planning_files_named_only_when_present(self):
        self.work.mkdir(parents=True)
        (self.work / "PLAN.md").write_text("p")
        (self.work / "EXECUTION.md").write_text("e")
        text = self.out(self.hook())
        self.assertIn("PLAN.md", text)
        self.assertIn("EXECUTION.md", text)
        self.assertNotIn("CHECKPOINTS.md", text)
        self.assertNotIn("'## Resume'", text)

    def test_fresh_resume_section(self):
        self.work.mkdir(parents=True)
        f = self.work / "EXECUTION.md"
        f.write_text("# x\n\n## Resume\nnext\n")
        self.assertIn("'## Resume'", self.out(self.hook()))
        old = time.time() - 3600
        os.utime(f, (old, old))
        self.assertNotIn("'## Resume'", self.out(self.hook()))

    def test_custom_instructions_take_precedence(self):
        self.assertIn("take precedence", self.out(self.hook(custom_instructions="focus on the API")))

    def test_empty_custom_instructions_do_not_count(self):
        for blank in ("", "   ", "\n\t "):
            with self.subTest(blank=repr(blank)):
                self.assertNotIn("take precedence", self.out(self.hook(custom_instructions=blank)))

    def test_planning_paths_use_forward_slashes(self):
        import compact_guide
        from pathlib import PureWindowsPath
        win = PureWindowsPath("C:\\proj\\.claude-work\\current")
        with mock.patch("paths.find_work_dir", return_value=win), \
                mock.patch.object(PureWindowsPath, "is_file", create=True, return_value=True), \
                mock.patch.object(compact_guide, "has_heading", return_value=False), \
                mock.patch.object(compact_guide, "recent_resume", return_value=False):
            text = compact_guide.build({"cwd": str(self.root)})
        self.assertIn("C:/proj/.claude-work/current/PLAN.md", text)
        self.assertNotIn("\\", text)

    def test_cwd_subfolder_finds_parent_planning_files(self):
        self.work.mkdir(parents=True)
        (self.work / "PLAN.md").write_text("p")
        sub = self.root / "src" / "deep"
        sub.mkdir(parents=True)
        self.assertIn("PLAN.md", self.out(self.hook(cwd=str(sub))))

    def test_git_boundary_stops_the_search(self):
        self.work.mkdir(parents=True)
        (self.work / "PLAN.md").write_text("p")
        inner = self.root / "inner"
        (inner / ".git").mkdir(parents=True)
        sub = inner / "src"
        sub.mkdir()
        self.assertNotIn("PLAN.md", self.out(self.hook(cwd=str(sub))))

    def test_claude_md_compact_instructions(self):
        (self.root / "CLAUDE.md").write_text("# Project\n\n## Compact instructions\nKeep the schema.\n")
        text = self.out(self.hook())
        self.assertIn("Compact instructions", text)
        self.assertIn("take precedence", text)

    def test_bad_input_still_prints_static_text_or_nothing(self):
        for stdin in (b"{not json", b"", b"[]", b"null", b"\xff\xfe",
                      {"trigger": "auto"}, {"cwd": 5}, {"cwd": None}, {"cwd": ["x"]},
                      {"cwd": str(self.root / "missing")}, {"cwd": "a\x00b"}):
            with self.subTest(stdin=stdin):
                self.out(stdin)

    def test_directory_where_a_file_should_be(self):
        (self.work / "EXECUTION.md").mkdir(parents=True)
        (self.root / "CLAUDE.md").mkdir()
        text = self.out(self.hook())
        self.assertNotIn("EXECUTION.md", text)

    @unittest.skipIf(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                     "chmod 000 is not enforced here")
    def test_unreadable_files(self):
        self.work.mkdir(parents=True)
        f = self.work / "EXECUTION.md"
        f.write_text("## Resume")
        c = self.root / "CLAUDE.md"
        c.write_text("## Compact instructions")
        f.chmod(0)
        c.chmod(0)
        try:
            self.out(self.hook())
        finally:
            f.chmod(0o644)
            c.chmod(0o644)

    def test_non_utf8_files(self):
        self.work.mkdir(parents=True)
        (self.work / "EXECUTION.md").write_bytes(b"\xff\xfe## Resume\n")
        (self.root / "CLAUDE.md").write_bytes(b"\xff\xfe\n## Compact instructions\n\xff")
        self.out(self.hook())

    def home_with(self, config):
        home = self.root / "synhome"
        home.mkdir(exist_ok=True)
        (home / "config.toml").write_text(config, encoding="utf-8")
        return str(home)

    def test_setting_false_prints_nothing(self):
        r = run(self.hook(), SYNAPSE_HOME=self.home_with("[continuation]\ncompact_guide = false\n"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"")

    def test_setting_true_or_unset_prints_guidance(self):
        for cfg in ("[continuation]\ncompact_guide = true\n", "[nudge]\ncalls = 5\n"):
            with self.subTest(cfg=cfg):
                self.assertIn("Worth keeping", self.out(self.hook(), SYNAPSE_HOME=self.home_with(cfg)))

    def test_invalid_config_still_prints_guidance(self):
        for cfg in ('[continuation]\ncompact_guide = "x"\n', "[continuation\n", "continuation = 3\n"):
            with self.subTest(cfg=cfg):
                self.assertIn("Worth keeping", self.out(self.hook(), SYNAPSE_HOME=self.home_with(cfg)))

    def test_usage_output_is_strict_utf8_under_cp1252(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
        env["PYTHONIOENCODING"] = "cp1252"
        r = subprocess.run([sys.executable, str(CLI), "compact-guide"], capture_output=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode("utf-8")  # strict
        self.assertIn("\u2014", text)

    def test_hooks_json_registers_precompact_without_matcher(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreCompact"]
        self.assertEqual(len(hooks), 1)
        self.assertNotIn("matcher", hooks[0])
        cmd = hooks[0]["hooks"][0]["command"]
        self.assertTrue("py.sh\" --optional " in cmd)
        self.assertTrue(cmd.endswith("compact-guide --hook"))


class DoctorPreCompactTests(unittest.TestCase):
    def test_other_precompact_hooks_are_listed(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / ".claude").mkdir()
            (t / ".claude" / "settings.json").write_text(json.dumps(
                {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
            plug = t / "plug"
            (plug / "hooks").mkdir(parents=True)
            (plug / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreCompact": [{"hooks": []}]}}))
            (t / "home").mkdir()
            (t / "home" / "settings.json").write_text(json.dumps({"enabledPlugins": {"other@m": True}}))
            (t / "home" / "plugins").mkdir()
            (t / "home" / "plugins" / "installed_plugins.json").write_text(json.dumps(
                {"plugins": {"other@m": [{"installPath": str(plug)}]}}))
            rep = doctor.Report()
            with mock.patch.object(doctor, "claude_dir", return_value=t / "home"):
                doctor.check_settings(rep, t)
            found = [i for i in rep.items if i["check"] == "precompact-hooks"]
            self.assertEqual(len(found), 2, rep.items)
            self.assertTrue(all(i["level"] == "warn" for i in found))


class DoctorAutocompactTests(unittest.TestCase):
    def run_check(self, user=None, project=None, env=None):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "home").mkdir()
            (t / ".claude").mkdir()
            if user is not None:
                (t / "home" / "settings.json").write_text(json.dumps(user))
            if project is not None:
                (t / ".claude" / "settings.json").write_text(json.dumps(project))
            clean = {k: v for k, v in os.environ.items()
                     if k not in ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "ANTHROPIC_MODEL")}
            clean.update(env or {})
            rep = doctor.Report()
            with mock.patch.object(doctor, "claude_dir", return_value=t / "home"), \
                    mock.patch.dict(os.environ, clean, clear=True), \
                    mock.patch.object(doctor, "MANAGED_SETTINGS", {}):
                doctor.check_settings(rep, t)
            return [i for i in rep.items if i["check"] == "autocompact-window"]

    def test_no_override_is_info(self):
        found = self.run_check()
        self.assertEqual([i["level"] for i in found], ["info"], found)
        self.assertIn("default applies", found[0]["detail"])

    def test_1m_model_without_override_warns(self):
        found = self.run_check(user={"model": "opus[1m]"})
        self.assertEqual([i["level"] for i in found], ["warn"], found)
        found = self.run_check(env={"ANTHROPIC_MODEL": "sonnet[1m]"})
        self.assertEqual([i["level"] for i in found], ["warn"], found)

    def test_settings_override_is_reported_with_value(self):
        found = self.run_check(user={"model": "opus[1m]"}, project={"autoCompactWindow": 300000})
        self.assertEqual([i["level"] for i in found], ["info"], found)
        self.assertIn("300000", found[0]["detail"])

    def test_per_model_override_from_autocompact_command(self):
        found = self.run_check(user={"modelSettings": {"opus": {"autoCompactWindow": 250000}}})
        self.assertIn("250000", found[0]["detail"])

    def test_env_override_is_reported(self):
        found = self.run_check(user={"model": "opus[1m]"}, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300k"})
        self.assertEqual([i["level"] for i in found], ["info"], found)
        self.assertIn("300k", found[0]["detail"])


if __name__ == "__main__":
    unittest.main()
