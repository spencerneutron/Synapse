import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import LIB, ROOT

from test_hooks import BASH

PY_SH = ROOT / "lib" / "py.sh"
CLI = ROOT / "lib" / "synapse" / "cli.py"
FILES = {"PLAN": "plan\n", "EXECUTION": "exec\n", "NOTES": "notes\n", "REPORT": "report\n"}


def run_cli(args, home, stdin=b"", **env):
    e = dict(os.environ, SYNAPSE_HOME=str(home), SYNAPSE_OPTIONAL="1")
    e.pop("SYNAPSE_DETACHED", None)
    e.update(env)
    cmd = [BASH, str(PY_SH), str(CLI), *args] if BASH else [sys.executable, str(CLI), *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, env=e)


class ArchiveAutoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.home, self.proj = t / "home", t / "proj"
        self.home.mkdir()
        (self.proj / ".claude-work" / "current").mkdir(parents=True)
        self.cur = self.proj / ".claude-work" / "current"
        for k, v in FILES.items():
            (self.cur / f"{k}.md").write_text(v)

    def hook(self, sid="s1", reason="other", cwd=None, **env):
        ev = {"session_id": sid, "reason": reason, "cwd": str(cwd or self.proj)}
        r = run_cli(["archive", "--auto", "--hook"], self.home, json.dumps(ev).encode(), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"")
        return r

    def archive_dir(self):
        found = list((self.home / "stores" / "main" / "archive").glob("*"))
        return found[0] if found else None

    def files(self):
        d = self.archive_dir()
        return sorted(p.name for p in d.glob("*.md")) if d else []

    def state_ids(self):
        d = self.archive_dir()
        return [json.loads(p.read_text()) for p in (d / ".auto").glob("*.json")] if d else []

    def test_first_archive_writes_all_and_state(self):
        self.hook()
        names = self.files()
        self.assertEqual(len(names), 4, names)
        sid = names[0].split("_", 1)[1][:-3]
        self.assertRegex(sid, r"^\d{4}-\d{2}-\d{2}-\d{4}$")
        for k, v in FILES.items():
            self.assertEqual((self.archive_dir() / f"{k}_{sid}.md").read_text(), v)
        (st,) = self.state_ids()
        self.assertEqual(st["id"], sid)
        self.assertEqual(st["reason"], "other")
        self.assertEqual(sorted(st["files"]), sorted(FILES))

    def test_unchanged_writes_nothing(self):
        self.hook()
        d = self.archive_dir()
        before = {p.name: p.stat().st_mtime_ns for p in d.glob("*.md")}
        self.hook()
        self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in d.glob("*.md")})
        self.assertEqual(len(self.files()), 4)

    def test_changed_overwrites_same_id_while_unprocessed(self):
        self.hook()
        sid = self.state_ids()[0]["id"]
        (self.cur / "EXECUTION.md").write_text("exec v2\n")
        self.hook()
        self.assertEqual(len(self.files()), 4)
        self.assertEqual((self.archive_dir() / f"EXECUTION_{sid}.md").read_text(), "exec v2\n")
        self.assertEqual(self.state_ids()[0]["id"], sid)

    def test_processed_gets_new_id(self):
        self.hook()
        sid = self.state_ids()[0]["id"]
        proc = self.archive_dir() / ".processed"
        proc.mkdir()
        (proc / f"{sid}.json").write_text("{}")
        (self.cur / "EXECUTION.md").write_text("exec v2\n")
        self.hook()
        self.assertEqual(len(self.files()), 8)
        self.assertNotEqual(self.state_ids()[0]["id"], sid)

    def test_matches_hand_made_archive(self):
        # NOTES.md stays in the working folder after end-session; it must not defeat the match
        r = run_cli(["archive", "--id", "2020-01-01-0000", "--workdir", str(self.proj)], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.files()), 3)
        self.hook()
        self.assertEqual(len(self.files()), 3)
        self.assertEqual(self.state_ids(), [])

    def test_no_planning_files(self):
        (self.cur / "PLAN.md").unlink()
        (self.cur / "EXECUTION.md").unlink()
        self.hook()
        self.assertEqual(self.files(), [])

    def test_setting_off(self):
        (self.home / "config.toml").write_text("[archive]\non_exit = false\n")
        self.hook()
        self.assertEqual(self.files(), [])

    def test_detached(self):
        self.hook(SYNAPSE_DETACHED="1")
        self.assertEqual(self.files(), [])

    def test_garbage_stdin(self):
        for data in (b"\xff\xfe not json", b"[1]", b""):
            r = run_cli(["archive", "--auto", "--hook"], self.home, data)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout, b"")
        self.assertEqual(self.files(), [])

    def test_shows_in_pending_and_files_untouched(self):
        before = {k: (self.cur / f"{k}.md").read_bytes() for k in FILES}
        self.hook()
        self.assertEqual(before, {k: (self.cur / f"{k}.md").read_bytes() for k in FILES})
        sys.path.insert(0, str(LIB))
        old = os.environ.get("SYNAPSE_HOME")
        os.environ["SYNAPSE_HOME"] = str(self.home)
        try:
            import paths
            from pending import pending_sessions
            r = paths.resolve(cwd=self.proj)
            self.assertEqual(pending_sessions(r), [self.state_ids()[0]["id"]])
        finally:
            if old is None:
                os.environ.pop("SYNAPSE_HOME")
            else:
                os.environ["SYNAPSE_HOME"] = old


if __name__ == "__main__":
    unittest.main()
