import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolated SYNAPSE_HOME, lib on sys.path)
import archive
import effort
import paths
from helpers import ROOT

CLI = ROOT / "lib" / "synapse" / "cli.py"


class EffortBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name).resolve()
        self.home, self.proj = t / "home", t / "proj"
        self.home.mkdir()
        (self.proj / ".git").mkdir(parents=True)
        patcher = mock.patch.dict(os.environ, {"SYNAPSE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        os.environ.pop("SYNAPSE_STORE", None)

    def cli(self, *args, sid=None, cwd=None):
        env = dict(os.environ, SYNAPSE_HOME=str(self.home))
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        if sid:
            env["CLAUDE_CODE_SESSION_ID"] = sid
        return subprocess.run([sys.executable, str(CLI), "effort", *args], cwd=cwd or self.proj,
                              capture_output=True, env=env, encoding="utf-8")

    def start(self, slug, title=None, sid=None):
        args = ["start", slug] + (["--title", title] if title else [])
        r = self.cli(*args, sid=sid)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def meta(self, slug):
        return effort.read(self.proj, slug)

    def archive_dir(self):
        return paths.resolve(cwd=self.proj).archive_dir


class VerbTests(EffortBase):
    def test_start_creates_folder_and_binds(self):
        r = self.start("alpha", "Alpha work", sid="s1")
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "Synapse effort started: alpha")
        self.assertEqual(lines[1], "folder: .claude-work/efforts/alpha")
        self.assertEqual(lines[2], "bound: this session")
        d = self.proj / ".claude-work" / "efforts" / "alpha"
        self.assertTrue((d / "PLAN.md").read_text(encoding="utf-8").startswith("# PLAN — Alpha work\n"))
        first = (d / "EXECUTION.md").read_text(encoding="utf-8").splitlines()[0]
        self.assertRegex(first, r"^# EXECUTION — Alpha work \(\d{4}-\d{2}-\d{2}\)$")
        self.assertEqual(self.meta("alpha")["status"], "active")
        self.assertEqual(paths.bound_effort(self.proj, "s1"), "alpha")

    def test_start_without_session_says_so(self):
        r = self.start("alpha")
        self.assertIn("bound: no session ID in this shell", r.stdout)
        self.assertIn("--effort <slug>", r.stdout)

    def test_start_refuses_existing_and_bad_slug(self):
        self.start("alpha")
        r = self.cli("start", "alpha")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error: "))
        self.assertIn("synapse effort resume alpha", r.stderr)
        r = self.cli("start", "Bad_Slug")
        self.assertEqual(r.returncode, 1)
        self.assertIn("invalid slug", r.stderr)

    def test_start_reuses_slug_of_closed_effort(self):
        self.start("alpha")
        self.assertEqual(self.cli("done", "alpha").returncode, 0)
        r = self.cli("start", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.meta("alpha")["status"], "active")
        self.assertEqual(len(list(paths.closed_dir(self.proj).iterdir())), 1)

    def test_resume_parked_clears_state_and_binds(self):
        self.start("alpha")
        self.cli("park", "alpha", "--reason", "later")
        self.assertEqual(self.meta("alpha")["status"], "parked")
        r = self.cli("resume", "alpha", sid="s2")
        self.assertEqual(r.stdout.splitlines()[0], "Synapse effort resumed: alpha")
        m = self.meta("alpha")
        self.assertEqual((m["status"], m["reason"], m["waiting_on"]), ("active", "", ""))
        self.assertEqual(paths.bound_effort(self.proj, "s2"), "alpha")

    def test_resume_unknown_lists_open(self):
        self.start("alpha")
        r = self.cli("resume", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("open: alpha", r.stderr)

    def test_resume_advises_about_another_session(self):
        self.start("alpha", sid="s1")
        r = self.cli("resume", "alpha", sid="s2")
        self.assertIn("another session was active", r.stdout)

    def test_wait_and_park(self):
        self.start("alpha")
        r = self.cli("wait", "alpha", "--on", "review")
        self.assertEqual(r.stdout.strip(), "Synapse effort waiting: alpha")
        self.assertEqual((self.meta("alpha")["status"], self.meta("alpha")["waiting_on"]), ("waiting", "review"))
        r = self.cli("park", "alpha")
        self.assertEqual(r.stdout.strip(), "Synapse effort parked: alpha")
        self.assertEqual(self.meta("alpha")["status"], "parked")

    def test_cancel_requires_reason(self):
        self.start("alpha")
        self.assertNotEqual(self.cli("cancel", "alpha").returncode, 0)
        self.assertEqual(self.meta("alpha")["status"], "active")
        r = self.cli("cancel", "alpha", "--reason", "dropped")
        self.assertEqual(r.stdout.splitlines()[0], "Synapse effort cancelled: alpha")
        self.assertEqual(self.meta("alpha")["status"], "cancelled")

    def test_list_all_and_json(self):
        self.start("alpha", "Alpha work")
        self.start("beta", "Beta work")
        self.cli("park", "beta", "--reason", "blocked")
        self.cli("done", "alpha", "--reason", "shipped")
        r = self.cli("list", "--all")
        self.assertIn("- beta [parked] Beta work (", r.stdout)
        self.assertIn(": blocked", r.stdout)
        self.assertRegex(r.stdout, r"- alpha \[done\] Alpha work \(archive \d{4}-\d{2}-\d{2}-\d{4}-alpha\)")
        data = json.loads(self.cli("list", "--all", "--json").stdout)
        self.assertEqual({e["slug"] for e in data}, {"alpha", "beta"})
        self.assertEqual(set(data[0]), {"slug", "title", "status", "waiting_on", "reason",
                                        "archive_id", "folder", "touched"})

    def test_migrate_dispatches_to_effort_migrate(self):
        fake = mock.Mock()
        fake.main.return_value = 7
        with mock.patch.dict(sys.modules, {"effort_migrate": fake}):
            self.assertEqual(effort.main(["migrate", "--x"]), 7)
        fake.main.assert_called_once_with(["--x"])


class CloseTests(EffortBase):
    def setUp(self):
        super().setUp()
        self.start("alpha", "Alpha work")
        self.folder = paths.effort_dir(self.proj, "alpha")

    def test_close_archives_with_slug_and_marker(self):
        r = self.cli("done", "alpha", "--reason", "shipped", "--json")
        out = json.loads(r.stdout)
        self.assertRegex(out["session_id"], r"^\d{4}-\d{2}-\d{2}-\d{4}-alpha$")
        self.assertEqual(out["missing"], [])
        ad = self.archive_dir()
        self.assertTrue((ad / f"PLAN_{out['session_id']}.md").is_file())
        self.assertIn("- (", (ad / f"PLAN_{out['session_id']}.md").read_text(encoding="utf-8"))
        r_ = paths.resolve(cwd=self.proj)
        self.assertEqual(archive.effort_of(r_, out["session_id"]), "alpha")
        self.assertIsNone(archive.effort_of(r_, "nope"))
        m = self.meta("alpha")
        self.assertEqual((m["status"], m["reason"], m["archive_id"]), ("done", "shipped", out["session_id"]))
        self.assertFalse((self.folder / ".closing").exists())

    def test_outcome_line_once_and_line_endings(self):
        plan = self.folder / "PLAN.md"
        plan.write_bytes(b"# PLAN - x\r\n\r\n## Outcome\r\n\r\n## Later\r\ntext\r\n")
        self.cli("done", "alpha", "--reason", "ok")
        data = plan.read_bytes()
        self.assertEqual(data.count(b"Done: ok"), 1)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))
        self.assertLess(data.index(b"Done: ok"), data.index(b"## Later"))
        line = effort._outcome_line("done", "ok", datetime.now())
        self.assertEqual(effort.add_outcome(data, line), data)

    def test_outcome_heading_added_at_end(self):
        plan = self.folder / "PLAN.md"
        plan.write_bytes(b"# PLAN - x\nbody")
        self.cli("cancel", "alpha", "--reason", "no longer needed")
        text = plan.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("## Outcome\n- (" + f"{datetime.now():%Y-%m-%d}" + ") Cancelled: no longer needed\n"))

    def test_archive_failure_leaves_effort_open(self):
        before = (self.folder / "PLAN.md").read_bytes()
        with mock.patch.object(archive, "copy_to_archive", side_effect=OSError("disk full")):
            with self.assertRaises(effort.EffortError):
                effort.close(self.proj, "alpha", "done", "x")
        self.assertEqual(self.meta("alpha")["status"], "active")
        self.assertEqual((self.folder / "PLAN.md").read_bytes(), before)
        self.assertFalse((self.folder / ".closing").exists())

    def test_closing_claim(self):
        claim = self.folder / ".closing"
        claim.write_text("x")
        r = self.cli("done", "alpha")
        self.assertEqual(r.returncode, 1)
        self.assertIn("being closed by another session", r.stderr)
        self.assertEqual(self.meta("alpha")["status"], "active")
        old = time.time() - 600
        os.utime(claim, (old, old))
        self.assertEqual(self.cli("done", "alpha").returncode, 0)
        self.assertFalse(claim.exists())

    def test_nothing_to_archive(self):
        (self.folder / "PLAN.md").unlink()
        (self.folder / "EXECUTION.md").unlink()
        out = json.loads(self.cli("done", "alpha", "--json").stdout)
        self.assertEqual(out["session_id"], "")
        self.assertEqual(self.meta("alpha")["archive_id"], "")

    def test_notes_merged_marker_not_archived(self):
        (self.folder / "NOTES.md").write_text("n\n<!-- merged into NOTES_2026-01-01-0000 -->\n", encoding="utf-8")
        out = json.loads(self.cli("done", "alpha", "--json").stdout)
        self.assertFalse((self.archive_dir() / f"NOTES_{out['session_id']}.md").exists())

    def test_second_close_gets_v2_id(self):
        now = datetime(2026, 1, 2, 3, 4).astimezone()
        a = effort.close(self.proj, "alpha", "done", "", now=now)
        self.assertEqual(a["session_id"], "2026-01-02-0304-alpha")
        self.start("alpha")   # reuse of the slug sweeps the closed folder
        b = effort.close(self.proj, "alpha", "done", "", now=now)
        self.assertEqual(b["session_id"], "2026-01-02-0304-alpha-v2")

    def test_move_waits_for_sweep_and_failure_is_harmless(self):
        self.cli("done", "alpha")
        self.assertTrue(self.folder.is_dir())          # not moved at close
        self.assertEqual(effort.index_text(self.proj), "")   # closed: not in the index
        old = datetime.now().astimezone().timestamp() - 7200
        meta = self.meta("alpha")
        meta["updated"] = datetime.fromtimestamp(old).astimezone().isoformat()
        (self.folder / "effort.json").write_text(json.dumps(meta), encoding="utf-8")
        with mock.patch("effort.os.rename", side_effect=OSError("locked")):
            effort.sweep_closed(self.proj)
        self.assertTrue(self.folder.is_dir())
        self.assertEqual(self.meta("alpha")["status"], "done")
        effort.sweep_closed(self.proj)
        self.assertFalse(self.folder.exists())
        moved = list(paths.closed_dir(self.proj).iterdir())
        self.assertEqual([m.name for m in moved], [meta["archive_id"]])
        self.assertEqual(effort.all_efforts(self.proj)[0]["slug"], "alpha")

    def test_sweep_force_and_collision(self):
        self.cli("done", "alpha")
        paths.closed_dir(self.proj).mkdir()
        aid = self.meta("alpha")["archive_id"]
        (paths.closed_dir(self.proj) / aid).mkdir()
        effort.sweep_closed(self.proj)
        self.assertTrue(self.folder.is_dir())   # too fresh
        effort.sweep_closed(self.proj, force_slug="alpha")
        self.assertTrue((paths.closed_dir(self.proj) / f"{aid}-2").is_dir())

    def test_start_errors_when_closed_folder_cannot_move(self):
        self.cli("done", "alpha")
        with mock.patch("effort.os.rename", side_effect=OSError("locked")):
            with mock.patch("effort.sys.argv", ["x"]):
                args = effort.parser().parse_args(["start", "alpha"])
                with mock.patch("effort.Path.cwd", return_value=self.proj):
                    with self.assertRaises(effort.EffortError) as cm:
                        effort.cmd_start(args)
        self.assertIn("a closed effort still holds", str(cm.exception))


class BindingTests(EffortBase):
    def test_binding_none_stale_and_garbage(self):
        self.start("alpha")
        self.assertIsNone(paths.bound_effort(self.proj, None))
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))
        effort.bind("s1", self.proj, "alpha")
        self.assertEqual(paths.bound_effort(self.proj, "s1"), "alpha")
        self.assertIsNone(paths.bound_effort(self.proj.parent / "other", "s1"))   # other root
        paths.effort_state("s1").write_text("{not json")
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))
        effort.bind("s1", self.proj, "alpha")
        self.cli("done", "alpha")
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))                 # closed

    def test_find_work_dir_follows_binding(self):
        self.start("alpha", sid="s1")
        sub = self.proj / "src"
        sub.mkdir()
        self.assertEqual(paths.find_work_dir(sub, session_id="s1"), paths.effort_dir(self.proj, "alpha"))
        self.assertEqual(paths.find_work_dir(sub, session_id="s9"), paths.work_dir(self.proj))
        self.assertEqual(paths.find_work_dir(sub, effort="zed"), paths.effort_dir(self.proj, "zed"))

    def test_two_sessions(self):
        effort.bind("s1", self.proj, "alpha")
        effort.bind("s2", self.proj, "alpha")
        self.assertIsNone(effort.others_on(self.proj, "alpha", "s1", within_s=-1))
        age = effort.others_on(self.proj, "alpha", "s1")
        self.assertIsNotNone(age)
        self.assertLess(age, 5)
        self.assertIsNone(effort.others_on(self.proj, "beta", "s1"))
        old = time.time() - 4000
        os.utime(paths.effort_state("s2"), (old, old))
        self.assertIsNone(effort.others_on(self.proj, "alpha", "s1"))

    def test_touch_updates_mtime_and_is_silent_when_missing(self):
        effort.touch("nobody")
        effort.bind("s1", self.proj, "alpha")
        old = time.time() - 1000
        os.utime(paths.effort_state("s1"), (old, old))
        effort.touch("s1")
        self.assertGreater(paths.effort_state("s1").stat().st_mtime, old + 500)

    def test_hook_bind(self):
        self.start("alpha")
        plan = self.proj / ".claude-work" / "efforts" / "alpha" / "PLAN.md"
        ev = {"session_id": "s1", "tool_name": "Edit", "tool_input": {"file_path": str(plan)}}
        effort.hook_bind({**ev, "agent_id": "a1"})
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))
        effort.hook_bind({**ev, "tool_name": "Read"})
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))
        other = str(plan.with_name("effort.json"))
        effort.hook_bind({**ev, "tool_input": {"file_path": other}})
        self.assertIsNone(paths.bound_effort(self.proj, "s1"))
        effort.hook_bind(ev)
        self.assertEqual(paths.bound_effort(self.proj, "s1"), "alpha")
        effort.hook_bind("garbage")   # never raises

    def test_stale_notice(self):
        self.start("alpha", sid="s1")
        self.assertEqual(effort.stale_notice("s1", self.proj), "")
        self.cli("done", "alpha", "--reason", "x")
        text = effort.stale_notice("s1", self.proj)
        self.assertIn("effort 'alpha' that this session was on is closed (done, archive ", text)
        self.assertFalse(paths.effort_state("s1").exists())
        self.assertEqual(effort.stale_notice("s1", self.proj), "")


class HandoffTests(EffortBase):
    def test_write_and_claim_once(self):
        self.start("alpha")
        effort.handoff_write(self.proj, "alpha", "old")
        self.assertEqual(len(paths.effort_handoffs(self.proj)), 1)
        self.assertIsNone(effort.handoff_claim(self.proj, "old"))   # same session
        self.assertEqual(effort.handoff_claim(self.proj, "new"), "alpha")
        self.assertIsNone(effort.handoff_claim(self.proj, "new"))   # claimed once
        self.assertEqual(paths.effort_handoffs(self.proj), [])

    def test_stale_handoff_ignored(self):
        self.start("alpha")
        effort.handoff_write(self.proj, "alpha", "old")
        f = paths.effort_handoff(self.proj, "old")
        d = json.loads(f.read_text(encoding="utf-8"))
        d["time"] -= 100
        f.write_text(json.dumps(d), encoding="utf-8")
        self.assertIsNone(effort.handoff_claim(self.proj, "new"))

    def test_exactly_one_rule(self):
        self.start("alpha")
        self.start("beta")
        effort.handoff_write(self.proj, "alpha", "old1")
        effort.handoff_write(self.proj, "beta", "old2")
        self.assertIsNone(effort.handoff_claim(self.proj, "new"))
        self.assertEqual(len(paths.effort_handoffs(self.proj)), 2)

    def test_closed_effort_not_claimed(self):
        self.start("alpha")
        effort.handoff_write(self.proj, "alpha", "old")
        self.cli("done", "alpha")
        self.assertIsNone(effort.handoff_claim(self.proj, "new"))


class IndexTests(EffortBase):
    def test_no_efforts_dir_is_empty(self):
        self.assertEqual(effort.index_text(self.proj), "")
        (self.proj / ".claude-work" / "current").mkdir(parents=True)
        (self.proj / ".claude-work" / "current" / "PLAN.md").write_text("p")
        self.assertEqual(effort.index_text(self.proj), "")

    def test_unbound(self):
        self.start("alpha", "Alpha   work")
        self.start("beta", "Beta")
        self.cli("wait", "beta", "--on", "finance sign-off")
        text = effort.index_text(self.proj)
        lines = text.splitlines()
        self.assertEqual(lines[0], "Synapse efforts in this project: 2 open, 0 parked. This session is on none yet.")
        self.assertIn("synapse effort resume <slug>", lines[1])
        self.assertIn("- alpha [active] Alpha work (just now)", lines)
        self.assertIn("- beta [waiting on: finance sign-off] Beta (just now)", lines)

    def test_bound_and_other_session(self):
        self.start("alpha", sid="s1")
        effort.bind("s2", self.proj, "alpha")
        text = effort.index_text(self.proj, "s1")
        self.assertIn("This session is on alpha.", text)
        self.assertIn("Its files are in .claude-work/efforts/alpha/; read no other effort's files.", text)
        self.assertTrue(text.splitlines()[2].endswith("(this session)"))
        text2 = effort.index_text(self.proj, "s3")
        self.assertIn("another session just now)", text2)

    def test_parked_only(self):
        self.start("alpha")
        self.cli("park", "alpha")
        lines = effort.index_text(self.proj).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("0 open, 1 parked", lines[0])

    def test_more_than_fifteen_and_cap(self):
        for i in range(17):
            self.start(f"e{i:02d}", "t" * 200)
        text = effort.index_text(self.proj)
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("- e")]), 15)
        self.assertIn("- and 2 more: `synapse effort list`", text)
        self.assertLessEqual(len(text), 4000)
        self.assertNotIn("t" * 81, text)

    def test_legacy_line(self):
        self.start("alpha")
        cur = self.proj / ".claude-work" / "current"
        cur.mkdir()
        (cur / "EXECUTION.md").write_text("e")
        self.assertTrue(effort.index_text(self.proj).splitlines()[-1].startswith("- (no effort) "))

    def test_folder_without_effort_json_is_not_an_effort(self):
        self.start("alpha")
        (paths.efforts_dir(self.proj) / "stray").mkdir()
        self.assertEqual([e["slug"] for e in effort.open_efforts(self.proj)], ["alpha"])

    def test_other_checkouts(self):
        wt = self.proj.parent / "wt"
        (wt / ".claude-work" / "efforts" / "side").mkdir(parents=True)
        (self.proj / ".git" / "worktrees" / "wt").mkdir(parents=True)
        (self.proj / ".git" / "worktrees" / "wt" / "gitdir").write_text(str(wt / ".git") + "\n")
        (wt / ".git").write_text(f"gitdir: {self.proj / '.git' / 'worktrees' / 'wt'}\n")
        effort.write(wt, "side", {"title": "Side work", "status": "active"})
        self.start("alpha")
        self.assertEqual([p.name for p in paths.sibling_roots(self.proj)], ["wt"])
        self.assertEqual([p.name for p in paths.sibling_roots(wt)], ["proj"])
        text = effort.index_text(self.proj)
        self.assertIn("Other checkouts of this repository", text)
        self.assertIn("- wt: side [active] Side work (", text)
        # a project with no efforts dir gets no index, siblings or not
        self.assertEqual(effort.index_text(wt.parent / "none"), "")


if __name__ == "__main__":
    unittest.main()
