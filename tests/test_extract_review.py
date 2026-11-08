"""B3/B4: the review ledger, `synapse extract review`, the accept setting in
check-candidates, and the pending hook's unreviewed-notes line."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from helpers import ROOT
import extract
import paths
import review
import vault_write

CLI = ROOT / "lib" / "synapse" / "cli.py"
SPEC = "---\ntype: pattern\ntitle: Quote paths\nproject: demo\n---\n## Problem\nx\n"


def run_cli(args, home, stdin=""):
    env = {**os.environ, "SYNAPSE_HOME": str(home)}
    return subprocess.run([sys.executable, str(CLI), *args], input=stdin.encode(),
                          capture_output=True, env=env)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        p = mock.patch.dict(os.environ, {"SYNAPSE_HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.tmp / "demo"
        self.proj.mkdir()
        cwd = os.getcwd()
        os.chdir(self.proj)
        self.addCleanup(os.chdir, cwd)
        self.r = paths.resolve(cwd=self.proj)
        for name, value in (("_vault_path_cache", None), ("VAULT_DIR", self.vault)):
            p = mock.patch.object(vault_write, name, value)
            p.start()
            self.addCleanup(p.stop)

    def create(self, title="Quote paths", batch=None):
        src = self.tmp / "spec.md"
        src.write_text(SPEC.replace("Quote paths", title), encoding="utf-8")
        with redirect_stdout(StringIO()):
            vault_write.cmd_create_note(Namespace(from_md=str(src), from_file=None,
                                                  on_conflict="error", review_batch=batch))

    def review_cmd(self, *argv):
        out = StringIO()
        with redirect_stdout(out):
            code = extract.main(["review", *argv])
        self.assertEqual(code, 0)
        return out.getvalue()


class LedgerTests(Base):
    def test_without_the_flag_nothing_is_written(self):
        self.create()
        self.assertFalse(paths.review_ledger(self.r).exists())

    def test_flag_appends_an_entry(self):
        self.create(batch="s1")
        data = json.loads(paths.review_ledger(self.r).read_text())
        self.assertIsNone(data["reviewed_at"])
        e = data["entries"][0]
        self.assertEqual((e["path"], e["title"], e["folder"], e["session"], e["project"]),
                         ("vault/Patterns/Quote paths.md", "Quote paths", "Patterns", "s1", "demo"))
        self.assertTrue(e["time"])


class ReviewCmdTests(Base):
    def test_empty(self):
        self.assertEqual(self.review_cmd().strip(), "Nothing to review since ever.")

    def test_lists_json_and_done(self):
        self.create("A note", "s1")
        text = self.review_cmd()
        self.assertIn("A note", text)
        self.assertIn("Patterns/A note.md", text)
        self.assertIn("extract supersede", text)
        data = json.loads(self.review_cmd("--json"))
        self.assertEqual(data["accept"], "auto")
        self.assertEqual(len(data["entries"]), 1)
        self.review_cmd("--done")
        self.assertTrue(review.load(self.r)["reviewed_at"])
        self.assertIn("Nothing to review since", self.review_cmd())
        self.assertEqual(json.loads(self.review_cmd("--json"))["entries"], [])

    def test_entries_after_done_are_listed_again(self):
        self.create("Old", "s1")
        ledger = review.load(self.r)
        ledger["reviewed_at"] = "2099-01-01T00:00:00+00:00"
        review.save(self.r, ledger)
        self.assertEqual(json.loads(self.review_cmd("--json"))["entries"], [])
        ledger["reviewed_at"] = "2000-01-01T00:00:00+00:00"
        review.save(self.r, ledger)
        self.assertEqual(len(json.loads(self.review_cmd("--json"))["entries"]), 1)


class AcceptSettingTests(Base):
    def run_cc(self):
        f = self.tmp / "c.json"
        f.write_text("[]")
        out = StringIO()
        with redirect_stdout(out):
            code = extract.main(["--db", str(self.tmp / "x.db"), "check-candidates", str(f),
                                 "--session", "s"])
        return code, out.getvalue()

    def test_accept_in_check_candidates(self):
        (self.tmp / "x.db").write_text("")
        with mock.patch.object(extract, "db_connect"), mock.patch.object(extract, "require_current"):
            self.assertEqual(json.loads(self.run_cc()[1])["accept"], "auto")
            (self.home / "config.toml").write_text('[extract]\naccept = "review"\n')
            self.assertEqual(json.loads(self.run_cc()[1])["accept"], "review")
            (self.home / "config.toml").write_text('[extract]\naccept = "maybe"\n')
            with self.assertRaises(SystemExit) as cm:
                self.run_cc()
            self.assertIn("accept", str(cm.exception))


class PendingLineTests(Base):
    def hook(self):
        out = run_cli(["pending", "--hook"], self.home,
                      json.dumps({"source": "startup", "cwd": str(self.proj)}))
        self.assertEqual(out.returncode, 0)
        return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"] if out.stdout else ""

    def seed(self, n):
        review.save(self.r, {"entries": [{"path": f"vault/Facts/f{i}.md", "title": f"f{i}",
                                          "folder": "Facts", "session": "s", "project": "demo",
                                          "time": "2026-10-0%dT10:00:00+00:00" % (i + 1)}
                                         for i in range(n)], "reviewed_at": None})

    def test_singular_plural_and_done(self):
        self.assertEqual(self.hook(), "")
        self.seed(1)
        self.assertEqual(self.hook(), "Synapse: 1 note was written by automatic extraction since "
                         "2026-10-01; `synapse extract review` lists it.")
        self.seed(3)
        self.assertIn("3 notes were written by automatic extraction since 2026-10-01", self.hook())
        self.assertEqual(run_cli(["extract", "review", "--done"], self.home).returncode, 0)
        self.assertEqual(self.hook(), "")

    def test_remind_off_is_silent(self):
        self.seed(2)
        (self.home / "config.toml").write_text("[extract]\nremind = false\n")
        self.assertEqual(self.hook(), "")

    def test_joins_the_pending_reminder(self):
        arch = self.r.archive_dir
        arch.mkdir(parents=True)
        (arch / "PLAN_2026-10-21-1000.md").write_text("x")
        self.seed(2)
        ctx = self.hook()
        self.assertIn("never extracted", ctx)
        self.assertIn("2 notes were written", ctx)


if __name__ == "__main__":
    unittest.main()
