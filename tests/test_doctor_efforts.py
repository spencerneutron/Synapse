import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401  (isolates SYNAPSE_HOME, sets sys.path)
import doctor


def make(root: Path, slug: str, status="active", write_json=True) -> Path:
    folder = root / ".claude-work" / "efforts" / slug
    folder.mkdir(parents=True)
    if write_json:
        (folder / "effort.json").write_text(json.dumps({"title": slug, "status": status}))
    return folder


def run_check(root: Path):
    rep = doctor.Report()
    doctor.check_efforts(rep, root)
    return rep.items


class DoctorEffortsTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def test_no_efforts_folder_prints_nothing(self):
        (self.root / ".claude-work" / "current").mkdir(parents=True)
        (self.root / ".claude-work" / "current" / "PLAN.md").write_text("# PLAN\n")
        self.assertEqual(run_check(self.root), [])

    def test_healthy_efforts_one_ok_row(self):
        make(self.root, "billing-export")
        make(self.root, "ci-cache", "parked")
        rows = run_check(self.root)
        self.assertEqual([r["level"] for r in rows], ["ok"], rows)
        self.assertIn("2 effort", rows[0]["detail"])

    def test_folder_without_effort_json_warns(self):
        make(self.root, "billing-export", write_json=False)
        rows = run_check(self.root)
        self.assertEqual([r["level"] for r in rows], ["warn"], rows)
        self.assertIn("billing-export", rows[0]["detail"])

    def test_unreadable_effort_json_warns(self):
        folder = make(self.root, "ci-cache")
        (folder / "effort.json").write_text("{not json")
        self.assertEqual([r["level"] for r in run_check(self.root)], ["warn"])

    def test_closed_folder_is_skipped(self):
        (self.root / ".claude-work" / "efforts" / "_closed" / "2026-11-15-1000-x").mkdir(parents=True)
        make(self.root, "ci-cache")
        self.assertEqual([r["level"] for r in run_check(self.root)], ["ok"])

    def test_stale_closing_claim_warns_fresh_does_not(self):
        folder = make(self.root, "ci-cache")
        claim = folder / ".closing"
        claim.write_text("")
        self.assertEqual([r["level"] for r in run_check(self.root)], ["ok"])
        old = time.time() - 2 * 3600
        os.utime(claim, (old, old))
        rows = run_check(self.root)
        self.assertEqual([r["level"] for r in rows], ["warn"], rows)
        self.assertIn(".closing", rows[0]["detail"])

    def test_closed_effort_left_in_place_is_info_after_a_day(self):
        folder = make(self.root, "ci-cache", "done")
        self.assertEqual([r["level"] for r in run_check(self.root)], ["ok"])
        old = time.time() - 2 * 86400
        os.utime(folder / "effort.json", (old, old))
        self.assertEqual([r["level"] for r in run_check(self.root)], ["info", "ok"])

    def test_large_current_plan_without_efforts_is_info(self):
        cur = self.root / ".claude-work" / "current"
        cur.mkdir(parents=True)
        (cur / "PLAN.md").write_text("line\n" * doctor.LARGE_PLAN_LINES)
        rows = run_check(self.root)
        self.assertEqual([r["level"] for r in rows], ["info"], rows)


def _git_ok() -> bool:
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(_git_ok(), "git missing")
class DoctorGitignoreEffortsTests(unittest.TestCase):
    def test_efforts_path_is_probed(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            make(root, "ci-cache")
            (root / ".gitignore").write_text(".claude-work/current/\n")
            rep = doctor.Report()
            doctor.check_gitignore(rep, root)
            self.assertEqual([i["level"] for i in rep.items], ["warn"], rep.items)
            (root / ".gitignore").write_text(".claude-work/\n")
            rep = doctor.Report()
            doctor.check_gitignore(rep, root)
            self.assertEqual(rep.items, [])


if __name__ == "__main__":
    unittest.main()
