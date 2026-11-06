import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from helpers import ROOT

CLI = ROOT / "lib" / "synapse" / "cli.py"
HOOK_RE = re.compile(r"Checkpoint written:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2} [+-]\d{2}:?\d{2})")
DOC = "# EXEC\n\n## Resume\n\n- Objective: x\n\n## Next\n\n1. a\n"


def stamp(cwd, *args):
    env = dict(os.environ, SYNAPSE_OPTIONAL="1")
    return subprocess.run([sys.executable, str(CLI), "checkpoint", *args],
                          cwd=cwd, capture_output=True, env=env)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / ".claude-work" / "current"
        self.work.mkdir(parents=True)
        self.file = self.work / "EXECUTION.md"

    def write(self, data: bytes):
        self.file.write_bytes(data)

    def test_stamp_inserted_under_heading(self):
        self.write(DOC.encode())
        r = stamp(self.root, "--stamp")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.file.read_text().splitlines()
        i = lines.index("## Resume")
        self.assertTrue(lines[i + 1].startswith("Checkpoint written: "))
        self.assertIn("Checkpoint stamped:", r.stdout.decode())

    def test_second_stamp_replaces(self):
        self.write(DOC.encode())
        stamp(self.root, "--stamp")
        stamp(self.root, "--stamp")
        self.assertEqual(self.file.read_text().count("Checkpoint written:"), 1)

    def test_outside_line_untouched(self):
        doc = DOC + "\nCheckpoint written: 2020-01-01 00:00 +00:00\n"
        self.write(doc.encode())
        stamp(self.root, "--stamp")
        text = self.file.read_text()
        self.assertEqual(text.count("Checkpoint written:"), 2)
        self.assertIn("Checkpoint written: 2020-01-01 00:00 +00:00", text)

    def test_missing_file_and_section(self):
        r = stamp(self.root, "--stamp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("EXECUTION.md", r.stderr.decode())
        self.assertFalse(self.file.exists())
        original = b"# EXEC\n\n## Next\n"
        self.write(original)
        r = stamp(self.root, "--stamp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Resume", r.stderr.decode())
        self.assertEqual(self.file.read_bytes(), original)

    def test_crlf_preserved(self):
        self.write(DOC.replace("\n", "\r\n").encode())
        stamp(self.root, "--stamp")
        data = self.file.read_bytes()
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertIn(b"Checkpoint written:", data)

    def test_stamp_format(self):
        self.write(DOC.encode())
        stamp(self.root, "--stamp")
        m = HOOK_RE.search(self.file.read_text())
        self.assertIsNotNone(m)
        datetime.strptime(m.group(1), "%Y-%m-%d %H:%M %z")

    def test_no_flag_prints_usage(self):
        r = stamp(self.root)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--stamp", r.stdout.decode())

    def test_skill_files(self):
        skill = (ROOT / "skills" / "checkpoint" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: checkpoint", skill)
        for s in ("synapse checkpoint --stamp", "/clear", "/compact"):
            self.assertIn(s, skill)
        end = (ROOT / "skills" / "end-session" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("merged into NOTES_", end)


if __name__ == "__main__":
    unittest.main()


class CheckpointEdgeTests(CheckpointTests):
    def run_apply(self, data):
        sys.path.insert(0, str(ROOT / "lib" / "synapse"))
        import checkpoint
        return checkpoint.apply(data, "2026-01-01 00:00 +00:00")

    def test_last_line_heading_uses_crlf(self):
        out = self.run_apply(b"# T\r\n\r\n## Resume")
        self.assertEqual(out, b"# T\r\n\r\n## Resume\r\nCheckpoint written: 2026-01-01 00:00 +00:00\r\n")

    def test_bom_preserved(self):
        out = self.run_apply(b"\xef\xbb\xbf## Resume\n- a\n")
        self.assertTrue(out.startswith(b"\xef\xbb\xbf## Resume\nCheckpoint written:"))

    def test_fenced_resume_ignored(self):
        self.assertIsNone(self.run_apply(b"# T\n```\n## Resume\n```\n"))
        out = self.run_apply(b"# T\n~~~\n## Resume\n~~~\n## Resume\nx\n")
        self.assertIn(b"~~~\n## Resume\nCheckpoint written:", out)
        self.assertEqual(out.count(b"Checkpoint written:"), 1)

    def test_section_end_with_tab_heading(self):
        data = b"## Resume\nCheckpoint written: old\n##\tNext\nCheckpoint written: keep\n"
        out = self.run_apply(data)
        self.assertEqual(out.count(b"Checkpoint written: keep"), 1)
        self.assertNotIn(b"old", out)

    def test_write_failure_exits_1(self):
        self.write(DOC.encode())
        os.chmod(self.work, 0o555)
        self.addCleanup(os.chmod, self.work, 0o755)
        if os.access(self.work, os.W_OK):
            self.skipTest("directory permissions not enforced")
        r = stamp(self.root, "--stamp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not write", r.stderr.decode())
        self.assertNotIn(b"Traceback", r.stderr)
        self.assertEqual(self.file.read_bytes(), DOC.encode())

    def test_symlink_survives(self):
        real = self.root / "real.md"
        real.write_bytes(DOC.encode())
        try:
            self.file.symlink_to(real)
        except (OSError, NotImplementedError):
            self.skipTest("no symlinks")
        r = stamp(self.root, "--stamp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.file.is_symlink())
        self.assertIn("Checkpoint written:", real.read_text())

    def test_skill_marker_rules(self):
        end = (ROOT / "skills" / "end-session" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("last non-blank line", end)
