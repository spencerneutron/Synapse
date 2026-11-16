import hashlib
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolated SYNAPSE_HOME, lib on sys.path)
import archive
import effort
import effort_migrate
import paths
from helpers import ROOT
from test_effort import EffortBase

HERE = Path(__file__).resolve().parent
PLAN = (HERE / "fixtures-plan-giant.md").read_bytes()
EXEC = (HERE / "fixtures-execution-giant.md").read_bytes()


def digest(folder: Path) -> dict:
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(folder.iterdir()) if f.is_file()}


class MigrateBase(EffortBase):
    def setUp(self):
        super().setUp()
        self.cur = self.proj / ".claude-work" / "current"
        self.cur.mkdir(parents=True)
        self.put("PLAN.md", PLAN)
        self.put("EXECUTION.md", EXEC)
        self.put("NOTES.md", b"# NOTES\n\n- a note\n")

    def put(self, name, data):
        (self.cur / name).write_bytes(data)

    def cli_migrate(self, *args):
        return self.cli("migrate", *args)

    def propose(self):
        r = self.cli_migrate()
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def apply(self, prop, *extra, name="proposal.json"):
        f = self.proj.parent / name
        f.write_text(json.dumps(prop), encoding="utf-8")
        return self.cli_migrate("--apply", str(f), *extra)

    def efforts_names(self):
        d = paths.efforts_dir(self.proj)
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []

    def plan_line(self, prefix, raw=PLAN):
        for n, l in enumerate(raw.decode().splitlines(), 1):
            if l.startswith(prefix):
                return n
        raise AssertionError(prefix)


class ProposeTests(MigrateBase):
    def test_covers_every_line_once(self):
        prop = self.propose()
        for key, name, raw in (("plan", "PLAN.md", PLAN), ("execution", "EXECUTION.md", EXEC)):
            seen = []
            for e in prop["efforts"] + [prop["history"]]:
                for a, b in e[key]:
                    seen.extend(range(a, b + 1))
            n = len(raw.splitlines())
            self.assertEqual(sorted(seen), list(range(1, n + 1)), name)
            self.assertEqual(prop["source"][name]["lines"], n)
            self.assertEqual(prop["source"][name]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertGreaterEqual(len(PLAN.splitlines()), 80)

    def test_open_and_finished_units(self):
        prop = self.propose()
        self.assertEqual([e["slug"] for e in prop["efforts"]],
                         ["phase-aa-tax-tables", "phase-ad-billing-export", "phase-ae-ci-cache",
                          "phase-h-webhooks", "phase-i-retry-queue"])
        by = {e["slug"]: e for e in prop["efforts"]}
        self.assertEqual(by["phase-ad-billing-export"]["title"], "Billing export")
        self.assertEqual(by["phase-ad-billing-export"]["status"], "active")
        start = self.plan_line("- **Phase AD")
        self.assertEqual(by["phase-ad-billing-export"]["plan"], [[start, self.plan_line("- **Phase AE") - 1]])
        hist = {n for a, b in prop["history"]["plan"] for n in range(a, b + 1)}
        # finished: Phase A (Progress checkbox, not Phase AA), B (done mark), F (boxes), G (check mark)
        for prefix in ("- **Phase A —", "- **Phase B", "## Phase F", "## Phase G", "## Purpose",
                       "## Constraints", "## Decision Log", "### Rejected", "## Backlog", "## Progress",
                       "## Outcome", "# PLAN"):
            self.assertIn(self.plan_line(prefix), hist, prefix)
        for prefix in ("- **Phase AA", "## Phase H", "## Phase I"):
            self.assertNotIn(self.plan_line(prefix), hist, prefix)
        self.assertEqual(prop["history"]["slug"], "history")
        self.assertEqual(prop["history"]["execution"], [[1, len(EXEC.splitlines())]])
        self.assertTrue(any("Resume" in n for n in prop["notes"]))

    def test_fenced_heading_is_not_a_unit(self):
        prop = self.propose()
        fake = self.plan_line("## Not a heading")
        inside = [e for e in prop["efforts"] if any(a <= fake <= b for a, b in e["plan"])]
        self.assertEqual([e["slug"] for e in inside], ["phase-i-retry-queue"])
        self.assertFalse(any("phase-z" in e["slug"] or "not-a-heading" in e["slug"] for e in prop["efforts"]))

    def test_fact_candidates(self):
        prop = self.propose()
        first = self.plan_line("- No downtime")
        self.assertEqual(prop["fact_candidates"], [
            {"line": first, "text": "No downtime during the export cutover."},
            {"line": first + 1, "text": "Keep the CI cache key stable across branches."},
            {"line": first + 2, "text": "Never log customer identifiers."}])

    def test_slugs_valid_and_unique(self):
        text = "# P\n\n## Strategy\n" + "".join(
            f"- **Phase A — Same name.**\n  - [ ] x\n" for _ in range(3)) + "## v2\n- [ ] y\n## " + "Long " * 20 + "\n"
        self.put("PLAN.md", text.encode())
        (paths.efforts_dir(self.proj) / "phase-a-same-name").mkdir(parents=True)
        (paths.efforts_dir(self.proj) / "history").mkdir()
        prop = self.propose()
        slugs = [e["slug"] for e in prop["efforts"]] + [prop["history"]["slug"]]
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertTrue(all(paths.valid_slug(s) for s in slugs), slugs)
        self.assertEqual(slugs[0], "phase-a-same-name-2")
        self.assertEqual(prop["history"]["slug"], "history-2")

    def test_proposal_is_read_only(self):
        before = digest(self.cur)
        self.propose()
        self.assertEqual(digest(self.cur), before)
        self.assertEqual(self.efforts_names(), [])

    def test_no_plan_is_an_error(self):
        (self.cur / "PLAN.md").unlink()
        r = self.cli_migrate()
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stderr.startswith("error: "), r.stderr)
        self.assertEqual(r.stdout, "")

    def test_help(self):
        r = self.cli_migrate("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--apply", r.stdout)


class ApplyTests(MigrateBase):
    def test_apply_writes_efforts_history_and_snapshot(self):
        prop = self.propose()
        before = digest(self.cur)
        r = self.apply(prop)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["created"], [e["slug"] for e in prop["efforts"]])
        self.assertEqual(out["history"], "history")
        self.assertFalse(out["retired"])
        self.assertTrue(re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{4}-pre-split", out["snapshot_id"]))
        self.assertEqual(digest(self.cur), before)
        # the snapshot
        arch = self.archive_dir()
        for prefix, raw in (("PLAN", PLAN), ("EXECUTION", EXEC)):
            self.assertEqual((arch / f"{prefix}_{out['snapshot_id']}.md").read_bytes(), raw)
        self.assertTrue((arch / f"NOTES_{out['snapshot_id']}.md").is_file())
        self.assertIsNone(archive.effort_of(paths.resolve(cwd=self.proj), out["snapshot_id"]))
        # an effort: header, verbatim range
        slug = "phase-ad-billing-export"
        folder = paths.effort_dir(self.proj, slug)
        a, b = prop["efforts"][1]["plan"][0]
        body = (folder / "PLAN.md").read_bytes()
        expected = b"".join(PLAN.splitlines(keepends=True)[a - 1:b])
        self.assertTrue(body.startswith(b"# PLAN \xe2\x80\x94 Billing export\n<!-- Split from .claude-work/current/PLAN.md on "))
        self.assertIn(f"snapshot {out['snapshot_id']}. -->".encode(), body)
        self.assertTrue(body.endswith(expected))
        self.assertRegex((folder / "EXECUTION.md").read_text(encoding="utf-8").splitlines()[0],
                         r"^# EXECUTION — Billing export \(\d{4}-\d{2}-\d{2}\)$")
        self.assertIn("## Next", (folder / "EXECUTION.md").read_text(encoding="utf-8"))
        self.assertEqual(effort.read(self.proj, slug)["status"], "active")
        # history
        meta = effort.read(self.proj, "history")
        self.assertEqual((meta["status"], meta["archive_id"], meta["reason"]),
                         ("done", out["snapshot_id"], "finished before the split"))
        self.assertNotIn("history", [e["slug"] for e in effort.open_efforts(self.proj)])
        self.assertEqual(len(effort.open_efforts(self.proj)), 5)
        hist = paths.effort_dir(self.proj, "history")
        self.assertIn(b"## Purpose", (hist / "PLAN.md").read_bytes())
        self.assertEqual((hist / "EXECUTION.md").read_bytes().split(b"\n", 2)[2], EXEC)
        self.assertEqual((hist / "NOTES.md").read_bytes(), b"# NOTES\n\n- a note\n")

    def test_edited_execution_assignment_and_dropped_ranges(self):
        prop = self.propose()
        resume = [self.plan_line("## Resume", EXEC), self.plan_line("## Status", EXEC) - 1]
        prop["history"]["execution"] = [[resume[1] + 1, len(EXEC.splitlines())]]
        prop["efforts"][1]["execution"] = [resume]
        dropped = prop["efforts"][0]["plan"]
        prop["efforts"][0]["plan"] = []          # an edited proposal drops the range
        r = self.apply(prop)
        self.assertEqual(r.returncode, 0, r.stderr)
        execm = (paths.effort_dir(self.proj, "phase-ad-billing-export") / "EXECUTION.md").read_bytes()
        self.assertTrue(execm.endswith(b"".join(EXEC.splitlines(keepends=True)[resume[0] - 1:resume[1]])))
        hp = (paths.effort_dir(self.proj, "history") / "PLAN.md").read_bytes()
        a, b = dropped[0]
        self.assertIn(b"".join(PLAN.splitlines(keepends=True)[a - 1:b]), hp)
        # nothing lost: EXECUTION lines are all in the two folders
        hx = (paths.effort_dir(self.proj, "history") / "EXECUTION.md").read_bytes()
        self.assertIn(b"## Status", hx)
        self.assertNotIn(b"## Resume", hx)

    def test_refusals_write_nothing(self):
        prop = self.propose()
        arch = self.archive_dir()

        def refused(p, text):
            r = self.apply(p)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn(text, r.stderr)
            self.assertEqual(self.efforts_names(), [])
            self.assertFalse(arch.is_dir() and any(arch.iterdir()))

        bad = json.loads(json.dumps(prop))
        bad["efforts"][0]["plan"] = [[1, 5]]                       # overlaps history
        refused(bad, "overlap")
        bad = json.loads(json.dumps(prop))
        bad["efforts"][1]["slug"] = bad["efforts"][0]["slug"]
        refused(bad, "twice")
        bad = json.loads(json.dumps(prop))
        bad["efforts"][0]["slug"] = "Bad Slug"
        refused(bad, "invalid slug")
        bad = json.loads(json.dumps(prop))
        bad["efforts"][0]["status"] = "waiting"
        refused(bad, "waiting_on")
        bad = json.loads(json.dumps(prop))
        bad["efforts"][0]["plan"] = [[1, 9999]]
        refused(bad, "range")
        bad = json.loads(json.dumps(prop))
        bad["version"] = 2
        refused(bad, "version")
        paths.effort_dir(self.proj, prop["efforts"][2]["slug"]).mkdir(parents=True)
        r = self.apply(prop)
        self.assertEqual(r.returncode, 1)
        self.assertIn("exists", r.stderr)
        self.assertEqual(self.efforts_names(), [prop["efforts"][2]["slug"]])
        self.assertFalse(arch.is_dir() and any(arch.iterdir()))

    def test_refuses_when_plan_changed(self):
        prop = self.propose()
        self.put("PLAN.md", PLAN + b"- late edit\n")
        r = self.apply(prop)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stderr.strip(),
                         "error: PLAN.md changed since the proposal; run `synapse effort migrate` again")
        self.assertEqual(self.efforts_names(), [])
        self.put("PLAN.md", PLAN)
        self.put("EXECUTION.md", EXEC + b"x\n")
        r = self.apply(prop)
        self.assertIn("EXECUTION.md changed", r.stderr)

    def test_rollback_removes_only_created_folders(self):
        prop = self.propose()
        real = effort._write_bytes
        calls = []

        def flaky(path, data):
            calls.append(path)
            if len(calls) == 4:
                raise OSError("disk full")
            return real(path, data)

        keep = paths.efforts_dir(self.proj) / "other"
        keep.mkdir(parents=True)
        with mock.patch.object(effort, "_write_bytes", flaky), \
                mock.patch.object(Path, "cwd", return_value=self.proj):
            with mock.patch("sys.stderr"):
                code = effort_migrate.main(["--apply", self._file(prop)])
        self.assertEqual(code, 1)
        self.assertEqual(self.efforts_names(), ["other"])

    def _file(self, prop):
        f = self.proj.parent / "p.json"
        f.write_text(json.dumps(prop), encoding="utf-8")
        return str(f)

    def test_crlf_is_kept(self):
        crlf = PLAN.replace(b"\n", b"\r\n")
        self.put("PLAN.md", crlf)
        self.put("EXECUTION.md", EXEC.replace(b"\n", b"\r\n"))
        prop = self.propose()
        self.assertEqual(prop["source"]["PLAN.md"]["lines"], len(PLAN.splitlines()))
        r = self.apply(prop)
        self.assertEqual(r.returncode, 0, r.stderr)
        for slug in ("phase-ad-billing-export", "history"):
            for name in ("PLAN.md", "EXECUTION.md"):
                data = (paths.effort_dir(self.proj, slug) / name).read_bytes()
                self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), (slug, name))
        a, b = prop["efforts"][1]["plan"][0]
        self.assertTrue((paths.effort_dir(self.proj, "phase-ad-billing-export") / "PLAN.md").read_bytes()
                        .endswith(b"".join(crlf.splitlines(keepends=True)[a - 1:b])))


class RetireTests(MigrateBase):
    def test_apply_with_retire_moves_files(self):
        prop = self.propose()
        r = self.apply(prop, "--retire-current")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["retired"])
        self.assertEqual(out["left"], [])
        dest = paths.closed_dir(self.proj) / out["snapshot_id"]
        self.assertEqual((dest / "PLAN.md").read_bytes(), PLAN)
        self.assertEqual((dest / "NOTES.md").read_bytes(), b"# NOTES\n\n- a note\n")
        self.assertEqual(sorted(p.name for p in self.cur.iterdir()), [])

    def test_retire_alone_reuses_matching_snapshot(self):
        out = json.loads(self.apply(self.propose()).stdout)
        r = self.cli_migrate("--retire-current")
        self.assertEqual(r.returncode, 0, r.stderr)
        again = json.loads(r.stdout)
        self.assertEqual(again["snapshot_id"], out["snapshot_id"])
        self.assertEqual(again["moved"], ["PLAN.md", "EXECUTION.md", "NOTES.md"])
        self.assertEqual([p.name for p in self.archive_dir().glob("PLAN_*")], [f"PLAN_{out['snapshot_id']}.md"])

    def test_retire_alone_snapshots_changed_current(self):
        out = json.loads(self.apply(self.propose()).stdout)
        self.put("PLAN.md", PLAN + b"- changed after the split\n")
        again = json.loads(self.cli_migrate("--retire-current").stdout)
        self.assertNotEqual(again["snapshot_id"], out["snapshot_id"])
        self.assertTrue(again["snapshot_id"].startswith(out["snapshot_id"]))   # -v2
        self.assertEqual((paths.closed_dir(self.proj) / again["snapshot_id"] / "PLAN.md").read_bytes(),
                         PLAN + b"- changed after the split\n")

    def test_retire_alone_needs_efforts_dir(self):
        r = self.cli_migrate("--retire-current")
        self.assertEqual(r.returncode, 1)
        self.assertIn("error: ", r.stderr)
        self.assertTrue((self.cur / "PLAN.md").is_file())

    def test_rename_failure_leaves_the_file(self):
        self.apply(self.propose())
        real = os.rename

        def fail_plan(src, dst):
            if Path(src).name == "PLAN.md":
                raise PermissionError("in use")
            return real(src, dst)

        with mock.patch.object(effort_migrate.os, "rename", fail_plan):
            out = effort_migrate.retire(self.proj, "2026-11-15-0900-pre-split", {})
        self.assertEqual(out["left"], ["PLAN.md"])
        self.assertEqual(out["moved"], ["EXECUTION.md", "NOTES.md"])
        self.assertEqual((self.cur / "PLAN.md").read_bytes(), PLAN)
        dest = paths.closed_dir(self.proj) / "2026-11-15-0900-pre-split"
        self.assertFalse((dest / "PLAN.md").exists())
        self.assertTrue((dest / "EXECUTION.md").is_file())


class SplitMarkerTests(MigrateBase):
    def test_marker_content(self):
        out = json.loads(self.apply(self.propose()).stdout)
        m = json.loads(paths.split_marker(self.proj).read_text(encoding="utf-8"))
        self.assertEqual(m["snapshot_id"], out["snapshot_id"])
        self.assertEqual(m["sources"], {"PLAN.md": hashlib.sha256(PLAN).hexdigest(),
                                        "EXECUTION.md": hashlib.sha256(EXEC).hexdigest()})
        self.assertRegex(m["time"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_marker_lists_only_existing_files(self):
        (self.cur / "EXECUTION.md").unlink()
        self.apply(self.propose())
        m = json.loads(paths.split_marker(self.proj).read_text(encoding="utf-8"))
        self.assertEqual(list(m["sources"]), ["PLAN.md"])

    def test_second_propose_and_apply_refuse(self):
        prop = self.propose()
        out = json.loads(self.apply(prop).stdout)
        before = self.efforts_names()
        archived = sorted(p.name for p in self.archive_dir().iterdir())
        for r in (self.cli_migrate(), self.apply(prop)):
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertEqual(r.stdout, "")
            self.assertEqual(r.stderr.strip(),
                             f"error: .claude-work/current/ was already split into efforts (snapshot "
                             f"{out['snapshot_id']}) and has not changed since. Move it away with "
                             "`synapse effort migrate --retire-current`, or pass --again to split it once more.")
        self.assertEqual(self.efforts_names(), before)
        self.assertEqual(sorted(p.name for p in self.archive_dir().iterdir()), archived)

    def test_again_splits_once_more(self):
        prop = self.propose()
        self.apply(prop)
        r = self.cli_migrate("--again")
        self.assertEqual(r.returncode, 0, r.stderr)
        prop2 = json.loads(r.stdout)
        self.assertEqual(prop2["history"]["slug"], "history-2")
        r = self.apply(prop2, "--again")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(paths.effort_dir(self.proj, "history-2").is_dir())

    def test_edited_plan_lifts_the_refusal(self):
        self.apply(self.propose())
        self.put("PLAN.md", PLAN + b"- added after the split\n")
        r = self.cli_migrate()
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_retire_reuses_marker_snapshot_and_removes_it(self):
        out = json.loads(self.apply(self.propose()).stdout)
        again = json.loads(self.cli_migrate("--retire-current").stdout)
        self.assertEqual(again["snapshot_id"], out["snapshot_id"])
        self.assertFalse(paths.split_marker(self.proj).exists())

    def test_retire_keeps_marker_when_a_file_is_left(self):
        self.apply(self.propose())
        real = os.rename

        def fail_plan(src, dst):
            if Path(src).name == "PLAN.md":
                raise PermissionError("in use")
            return real(src, dst)

        with mock.patch.object(effort_migrate.os, "rename", fail_plan):
            out = effort_migrate.retire(self.proj, "x-pre-split", {})
        self.assertEqual(out["left"], ["PLAN.md"])
        self.assertTrue(paths.split_marker(self.proj).is_file())

    def test_apply_with_retire_leaves_no_marker(self):
        self.apply(self.propose(), "--retire-current")
        self.assertFalse(paths.split_marker(self.proj).exists())


class RollbackAndShapeTests(MigrateBase):
    def run_main(self, prop, *extra):
        with mock.patch.object(Path, "cwd", return_value=self.proj), mock.patch("sys.stderr") as err, \
                mock.patch("sys.stdout"):
            code = effort_migrate.main(["--apply", self._file(prop), *extra])
        return code, "".join(str(c.args[0]) for c in err.write.call_args_list)

    def _file(self, prop):
        f = self.proj.parent / "p.json"
        f.write_text(json.dumps(prop), encoding="utf-8")
        return str(f)

    def test_rollback_removes_empty_efforts_dir_and_no_marker(self):
        prop = self.propose()
        real = effort._write_bytes
        n = []

        def flaky(path, data):
            n.append(path)
            if len(n) == 3:
                raise OSError("disk full")
            return real(path, data)

        self.assertFalse(paths.efforts_dir(self.proj).exists())
        with mock.patch.object(effort, "_write_bytes", flaky):
            code, _ = self.run_main(prop)
        self.assertEqual(code, 1)
        self.assertFalse(paths.efforts_dir(self.proj).exists())

    def test_marker_write_failure_rolls_back_everything(self):
        prop = self.propose()
        with mock.patch.object(effort_migrate, "_write_marker", side_effect=OSError("nope")):
            code, _ = self.run_main(prop)
        self.assertEqual(code, 1)
        self.assertFalse(paths.efforts_dir(self.proj).exists())

    def test_preexisting_efforts_dir_is_kept(self):
        keep = paths.efforts_dir(self.proj) / "other"
        keep.mkdir(parents=True)
        prop = self.propose()
        with mock.patch.object(effort_migrate, "_write_marker", side_effect=OSError("nope")):
            self.run_main(prop)
        self.assertEqual(self.efforts_names(), ["other"])

    def test_folder_created_by_another_session_is_not_overwritten(self):
        prop = self.propose()
        plan = effort_migrate.validate(self.proj, prop)        # passes: nothing exists yet
        victim = prop["efforts"][1]["slug"]
        mine = paths.effort_dir(self.proj, victim)
        mine.mkdir(parents=True)
        (mine / "PLAN.md").write_bytes(b"theirs\n")
        with mock.patch.object(effort_migrate, "validate", return_value=plan):
            code, err = self.run_main(prop)
        self.assertEqual(code, 1)
        self.assertIn("error: ", err)
        self.assertEqual((mine / "PLAN.md").read_bytes(), b"theirs\n")
        self.assertEqual(self.efforts_names(), [victim])        # the earlier one was rolled back
        self.assertFalse(paths.split_marker(self.proj).exists())

    def test_hostile_shapes_fail_cleanly(self):
        prop = self.propose()

        def mutate(fn):
            p = json.loads(json.dumps(prop))
            fn(p)
            return p

        cases = [
            lambda p: p["source"].__setitem__("EXECUTION.md", {"sha256": None}),
            lambda p: p["source"].__setitem__("PLAN.md", {"sha256": 5}),
            lambda p: p.__setitem__("source", []),
            lambda p: p["source"].__setitem__("PLAN.md", "abc"),
            lambda p: p["efforts"][0].__setitem__("plan", "1-5"),
            lambda p: p["efforts"][0].__setitem__("plan", ["1-5"]),
            lambda p: p["efforts"][0].__setitem__("plan", [[1, "5"]]),
            lambda p: p["efforts"][0].__setitem__("title", ["x"]),
            lambda p: p["efforts"][0].__setitem__("title", "bad \ud800 title"),
            lambda p: p["efforts"][0].__setitem__("waiting_on", {"a": 1}),
            lambda p: p["efforts"][0].__setitem__("status", ["active"]),
            lambda p: p["efforts"][0].__setitem__("slug", 7),
            lambda p: p["efforts"].__setitem__(0, "nope"),
            lambda p: p.__setitem__("efforts", {}),
            lambda p: p.__setitem__("history", []),
            lambda p: p["history"].__setitem__("execution", {"a": [1, 2]}),
        ]
        for i, fn in enumerate(cases):
            code, err = self.run_main(mutate(fn))
            self.assertEqual(code, 1, i)
            self.assertTrue(err.startswith("error: "), (i, err))
            self.assertEqual(self.efforts_names(), [], i)
            self.assertFalse(self.archive_dir().is_dir() and any(self.archive_dir().iterdir()), i)
        # a null sha with the file missing
        (self.cur / "EXECUTION.md").unlink()
        p = mutate(lambda p: p["source"].__setitem__("EXECUTION.md", {"sha256": None}))
        code, err = self.run_main(p)
        self.assertEqual(code, 1)
        self.assertEqual(self.efforts_names(), [])


if __name__ == "__main__":
    unittest.main()
