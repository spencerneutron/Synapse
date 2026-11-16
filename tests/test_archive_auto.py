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

    def test_manual_archive_copies_artifacts(self):
        (self.cur / "ARTIFACTS.md").write_text("- [A](https://claude.ai/artifact/a1)\n")
        r = run_cli(["archive", "--id", "2020-01-01-0000", "--workdir", str(self.proj)], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.archive_dir() / "ARTIFACTS_2020-01-01-0000.md").read_text(),
                         "- [A](https://claude.ai/artifact/a1)\n")
        self.assertEqual(len(self.files()), 4)

    def test_equal_artifacts_skip_and_artifacts_only_change_archives(self):
        art = "- [A](https://claude.ai/artifact/a1)\n"
        (self.cur / "ARTIFACTS.md").write_text(art)
        r = run_cli(["archive", "--id", "2020-01-01-0000", "--workdir", str(self.proj)], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.hook()   # same files as the newest archive: skip
        self.assertEqual(len(self.files()), 4)
        self.assertEqual(self.state_ids(), [])
        (self.cur / "ARTIFACTS.md").write_text(art + "- [B](https://claude.ai/artifact/b2)\n")
        self.hook()   # only the artifacts changed: archive
        self.assertEqual(len(self.files()), 9)   # the 4 hand-made + all 5 auto
        self.assertEqual(len(self.state_ids()), 1)

    def manual(self, sid):
        r = run_cli(["archive", "--id", sid, "--workdir", str(self.proj)], self.home)
        self.assertEqual(r.returncode, 0, r.stderr)

    def art(self, name):
        return (self.archive_dir() / name).read_text()

    def publish(self, *links):
        from artifacts import record
        record(self.cur, [(f"https://claude.ai/artifact/{u}", t) for u, t in links])

    def test_segments_manual_then_new_publish_archives_only_new_link(self):
        self.publish(("a1", "A"))
        self.manual("2020-01-01-0000")
        self.assertEqual(self.art("ARTIFACTS_2020-01-01-0000.md"), "- [A](https://claude.ai/artifact/a1)\n")
        self.assertNotIn("<!--", self.art("ARTIFACTS_2020-01-01-0000.md"))
        self.assertIn("<!-- archived: 2020-01-01-0000 -->", (self.cur / "ARTIFACTS.md").read_text())
        self.publish(("b2", "B"))
        self.hook()
        auto = [n for n in self.files() if n.startswith("ARTIFACTS_") and "2020" not in n]
        self.assertEqual(len(auto), 1)
        self.assertEqual(self.art(auto[0]), "- [B](https://claude.ai/artifact/b2)\n")

    def test_segments_manual_then_session_end_with_nothing_new_skips(self):
        self.publish(("a1", "A"))
        self.manual("2020-01-01-0000")
        self.hook()
        self.assertEqual(len(self.files()), 4)
        self.assertEqual(self.state_ids(), [])

    def test_segments_republished_url_gets_fresh_line_in_next_archive(self):
        self.publish(("a1", "A"))
        self.manual("2020-01-01-0000")
        self.publish(("a1", "A again"))
        self.hook()
        auto = [n for n in self.files() if n.startswith("ARTIFACTS_") and "2020" not in n]
        self.assertEqual(self.art(auto[0]), "- [A again](https://claude.ai/artifact/a1)\n")

    def test_segments_reused_id_merges(self):
        self.publish(("a1", "A"), ("b2", "B"))
        self.hook()
        sid = self.state_ids()[0]["id"]
        self.publish(("b2", "B new"), ("c3", "C"))
        (self.cur / "EXECUTION.md").write_text("exec v2\n")
        self.hook()
        self.assertEqual(self.state_ids()[0]["id"], sid)
        self.assertEqual(self.art(f"ARTIFACTS_{sid}.md"),
                         "- [A](https://claude.ai/artifact/a1)\n- [B new](https://claude.ai/artifact/b2)\n"
                         "- [C](https://claude.ai/artifact/c3)\n")
        self.hook()   # nothing changed: no second archive, no marker-triggered rerun
        self.assertEqual(len(self.files()), 5)

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


class ArchiveEffortTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.home, self.proj = t / "home", t / "proj"
        (self.home / "state").mkdir(parents=True)
        self.cur = self.proj / ".claude-work" / "current"
        self.cur.mkdir(parents=True)
        self.efforts = self.proj / ".claude-work" / "efforts"
        self.env = {"CLAUDE_CODE_SESSION_ID": ""}

    def effort(self, slug, text="plan\n", status="active"):
        d = self.efforts / slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "effort.json").write_text(json.dumps({"slug": slug, "status": status}))
        (d / "PLAN.md").write_text(text)
        (d / "EXECUTION.md").write_text("exec " + text)
        return d

    def bind(self, sid, slug):
        (self.home / "state" / f"effort-{sid}.json").write_text(
            json.dumps({"root": os.path.abspath(str(self.proj)), "slug": slug}))

    def hook(self, sid, reason="other", **env):
        ev = {"session_id": sid, "reason": reason, "cwd": str(self.proj)}
        r = run_cli(["archive", "--auto", "--hook"], self.home, json.dumps(ev).encode(), **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"")

    def adir(self):
        found = list((self.home / "stores" / "main" / "archive").glob("*"))
        return found[0] if found else None

    def ids(self):
        d = self.adir()
        return sorted({p.name.split("_", 1)[1][:-3] for p in d.glob("PLAN_*.md")}) if d else []

    def archive(self, *args, cwd=None, **env):
        e = dict(self.env, **env)
        r = run_cli(["archive", *args], self.home, **e) if cwd is None else \
            run_cli(["archive", "--workdir", str(cwd), *args], self.home, **e)
        return r

    def test_manual_from_subfolder_finds_folder(self):
        (self.cur / "PLAN.md").write_text("p\n")
        sub = self.proj / "a" / "b"
        sub.mkdir(parents=True)
        r = self.archive(cwd=sub, **{"SYNAPSE_OPTIONAL": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertIsNone(out["effort"])
        self.assertEqual(Path(out["folder"]), self.cur)
        self.assertEqual(len(out["copied"]), 1)

    def test_manual_effort_flag(self):
        self.effort("alpha")
        r = self.archive("--effort", "alpha", cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["effort"], "alpha")
        self.assertEqual(Path(out["folder"]), self.efforts / "alpha")
        self.assertRegex(out["session_id"], r"^\d{4}-\d{2}-\d{2}-\d{4}-alpha$")
        marker = self.adir() / ".effort" / out["session_id"]
        self.assertEqual(marker.read_text().strip(), "alpha")

    def test_manual_effort_flag_unknown(self):
        self.effort("alpha")
        (self.efforts / "bare").mkdir()
        for slug in ("nope", "bare"):
            r = self.archive("--effort", slug, cwd=self.proj)
            self.assertEqual(r.returncode, 1)
            self.assertIn("alpha", r.stderr.decode())
        self.assertIsNone(self.adir())

    def test_manual_bound_by_env_and_explicit_id_still_marked(self):
        self.effort("alpha")
        self.bind("sess1", "alpha")
        r = self.archive("--id", "mine", cwd=self.proj, CLAUDE_CODE_SESSION_ID="sess1")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["session_id"], out["effort"]), ("mine", "alpha"))
        self.assertTrue((self.adir() / ".effort" / "mine").is_file())

    def test_auto_bound_goes_to_effort_with_own_state(self):
        d = self.effort("alpha")
        self.bind("s1", "alpha")
        self.hook("s1")
        (sid,) = self.ids()
        self.assertRegex(sid, r"^\d{4}-\d{2}-\d{2}-\d{4}-alpha$")
        self.assertEqual((self.adir() / f"PLAN_{sid}.md").read_text(), "plan\n")
        self.assertEqual((self.adir() / ".effort" / sid).read_text().strip(), "alpha")
        self.assertTrue((self.adir() / ".auto" / "s1--alpha.json").is_file())
        self.assertFalse((self.adir() / ".auto" / "s1.json").exists())
        before = (self.adir() / f"PLAN_{sid}.md").stat().st_mtime_ns
        self.hook("s1")   # unchanged: skipped
        self.assertEqual(self.ids(), [sid])
        self.assertEqual(before, (self.adir() / f"PLAN_{sid}.md").stat().st_mtime_ns)
        (d / "PLAN.md").write_text("plan2\n")
        self.hook("s1")   # changed: same ID reused
        self.assertEqual(self.ids(), [sid])
        self.assertEqual((self.adir() / f"PLAN_{sid}.md").read_text(), "plan2\n")

    def test_effort_compared_with_its_own_newest_archive(self):
        self.effort("alpha", "A\n")
        self.effort("beta", "B\n")
        self.bind("sa", "alpha")
        self.bind("sb", "beta")
        self.hook("sa")
        self.hook("sb")
        n = len(self.ids())
        self.assertEqual(n, 2)
        self.hook("sa")   # alpha unchanged though beta's archive is newest
        self.assertEqual(len(self.ids()), 2)
        self.hook("sa", reason="resume")
        self.assertEqual(len(self.ids()), 2)

    def test_current_unchanged_not_archived_again_when_effort_is_newest(self):
        (self.cur / "PLAN.md").write_text("cur\n")
        (self.cur / "EXECUTION.md").write_text("cexec\n")
        self.hook("plain")
        self.assertEqual(len(self.ids()), 1)
        self.effort("alpha", "A\n")
        self.bind("sa", "alpha")
        self.hook("sa")
        self.assertEqual(len(self.ids()), 2)
        self.hook("other-session")   # unbound: current/, unchanged since its unmarked archive
        self.assertEqual(len(self.ids()), 2)

    def test_cli_from_subfolder_uses_root_project(self):
        (self.cur / "PLAN.md").write_text("cur\n")
        sub = self.proj / "pkg" / "deep"
        sub.mkdir(parents=True)
        r = run_cli(["archive", "--workdir", str(sub)], self.home, b"")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["project"], "proj")

    def test_hook_effort_session_from_subfolder_uses_root_project(self):
        self.effort("alpha", "A\n")
        self.bind("sa", "alpha")
        sub = self.proj / "pkg"
        sub.mkdir()
        ev = {"session_id": "sa", "reason": "other", "cwd": str(sub)}
        r = run_cli(["archive", "--auto", "--hook"], self.home, json.dumps(ev).encode())
        self.assertEqual(r.returncode, 0, r.stderr)
        (a,) = (self.home / "stores").glob("*/archive/*")
        self.assertEqual(a.name, "proj")

    def test_no_efforts_dir_behaves_as_before(self):
        (self.cur / "PLAN.md").write_text("cur\n")
        self.hook("s1")
        self.hook("s2")   # same content as the newest archive
        (sid,) = self.ids()
        self.assertRegex(sid, r"^\d{4}-\d{2}-\d{2}-\d{4}$")
        self.assertFalse((self.adir() / ".effort").exists())

    def handoffs(self):
        return list((self.home / "state").glob("effort-handoff-*.json"))

    def test_clear_writes_handoff_even_with_nothing_to_archive_or_setting_off(self):
        self.effort("alpha")
        self.bind("s1", "alpha")
        (self.home / "config.toml").write_text("[archive]\non_exit = false\n")
        self.hook("s1", reason="clear")
        (h,) = self.handoffs()
        data = json.loads(h.read_text())
        self.assertEqual((data["slug"], data["from"]), ("alpha", "s1"))
        self.assertEqual(self.ids(), [])

    def test_auto_bound_session_archives_its_effort(self):
        self.effort("alpha", "alpha plan\n")
        (self.cur / "NOTES.md").write_text("leftover\n")   # no PLAN/EXECUTION: does not block
        ev = {"session_id": "n1", "hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.proj)}
        r = run_cli(["nudge", "--hook"], self.home, json.dumps(ev).encode())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"This session is on alpha", r.stdout)
        self.hook("n1")
        (sid,) = self.ids()
        self.assertEqual((self.adir() / f"PLAN_{sid}.md").read_text(), "alpha plan\n")

    def test_handoff_only_for_bound_clear(self):
        self.effort("alpha")
        self.bind("s1", "alpha")
        self.hook("s1", reason="other")
        self.hook("unbound", reason="clear")
        self.assertEqual(self.handoffs(), [])
        self.hook("s1", reason="clear")
        self.assertEqual(len(self.handoffs()), 1)


if __name__ == "__main__":
    unittest.main()
