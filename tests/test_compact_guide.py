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
        self.assertIn("take precedence", self.out(self.hook(custom_instructions="")))

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

    def test_hooks_json_registers_precompact_without_matcher(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]["PreCompact"]
        self.assertEqual(len(hooks), 1)
        self.assertNotIn("matcher", hooks[0])
        cmd = hooks[0]["hooks"][0]["command"]
        self.assertTrue(cmd.startswith("SYNAPSE_OPTIONAL=1 "))
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


if __name__ == "__main__":
    unittest.main()
