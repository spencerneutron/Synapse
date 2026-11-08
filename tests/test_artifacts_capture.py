import json
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import LIB, ROOT  # noqa: F401  (sets up sys.path and SYNAPSE_HOME)
from test_gate import GateBase, run_gate

import artifacts
import continuation
import gate

A = "https://claude.ai/artifact/"
FIXTURE = Path(__file__).resolve().parent / "artifacts-sample.jsonl"
WASH_ID = "e6084f8d-293b-4b0e-afd6-a5fd3ec0bd31"


def turn_of(path=FIXTURE):
    turn = []
    continuation.scan(str(path), False, turn)
    return turn


class FromTurnTests(unittest.TestCase):
    def test_fixture_publishes_only(self):
        self.assertEqual(artifacts.from_turn(turn_of()), [
            (A + "WASHWASHWASH1", "Wash Lab"),
            (A + "PLAINPLAIN001", "plain.html"),
            (A + "WASHWASHWASH1", "Wash Lab v2"),
        ])

    def test_previous_turn_not_read(self):
        urls = [u for u, _ in artifacts.from_turn(turn_of())]
        self.assertNotIn(A + "OLDOLDOLDOLD1", urls)
        self.assertNotIn(A + "OPENEDOPENED1", urls)
        self.assertNotIn(A + "TYPETYPETYPE1", urls)
        self.assertNotIn(A + "READREADREAD1", urls)

    def test_no_turn_when_not_asked(self):
        self.assertEqual(continuation.scan(str(FIXTURE)), continuation.scan(str(FIXTURE), False, None))

    def test_scan_result_unchanged_by_turn(self):
        self.assertEqual(continuation.scan(str(FIXTURE), True), continuation.scan(str(FIXTURE), True, []))

    def test_missing_file(self):
        turn = []
        self.assertEqual(continuation.scan("/nonexistent/x.jsonl", False, turn), (None, None))
        self.assertEqual(turn, [])

    def test_url_from_result_text_without_tool_use_result(self):
        t = turn_of()
        items = artifacts.from_turn([e for e in t if "toolUseResult" not in e or
                                     e["message"]["content"][0]["tool_use_id"] != "toolu_1"])
        self.assertIn((A + "PLAINPLAIN001", "plain.html"), items)

    def test_type_url_never_a_published_url(self):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Artifact",
                 "input": {"type_url": A + "TYPETYPETYPE1", "title": "Deck"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "Created, no files yet"}]}},
        ]
        self.assertEqual(artifacts.from_turn(entries), [])
        self.assertEqual(artifacts.from_message(f"see {A}TYPETYPETYPE1", entries), [])

    def test_asset_upload_not_recorded(self):
        entries = [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1", "name": "Artifact",
                 "input": {"url": A + "ZZZZZZZZZZZZ", "asset": True, "file_path": "/w/a.png"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": f"Uploaded at {A}ZZZZZZZZZZZZ"}]}},
        ]
        self.assertEqual(artifacts.from_turn(entries), [])


class FromMessageTests(unittest.TestCase):
    def test_urls_in_order_without_repeats(self):
        text = f"One {A}AAAA1111 and https://claude.ai/code/artifact/bbbb-2222, again {A}AAAA1111."
        self.assertEqual(artifacts.from_message(text, []),
                         [A + "AAAA1111", "https://claude.ai/code/artifact/bbbb-2222"])

    def test_same_artifact_code_url_excluded(self):
        text = f"{A}WASHWASHWASH1 also https://claude.ai/code/artifact/{WASH_ID} and {A}OTHEROTHER01"
        self.assertEqual(artifacts.from_message(text, turn_of()),
                         [A + "WASHWASHWASH1", A + "OTHEROTHER01"])

    def test_read_or_open_only_is_not_a_publish(self):
        entries = []
        for i, act in enumerate(("read", "open")):
            entries += [
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"t{i}",
                 "name": "Artifact", "input": {"action": act, "url": f"{A}LOOKED{i}"}}]}},
                {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"t{i}",
                 "content": "ok"}]}},
            ]
        text = f"{A}LOOKED0 {A}LOOKED1 {A}OTHEROTHER01"
        self.assertEqual(artifacts.from_message(text, entries), [A + "OTHEROTHER01"])
        self.assertEqual(artifacts.from_turn(entries), [])

    def test_empty_and_garbage(self):
        self.assertEqual(artifacts.from_message(None, []), [])
        self.assertEqual(artifacts.from_message("no links https://example.com/artifact/x", []), [])


class RecordTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name) / "p" / ".claude-work" / "current"
        self.f = self.work / "ARTIFACTS.md"

    def test_no_create_when_empty(self):
        self.assertFalse(artifacts.record(self.work, []))
        self.assertFalse(self.work.exists())

    def test_file_name_title_never_renames_a_known_line(self):
        artifacts.record(self.work, [(A + "AAAA1111", "Real Title")])
        entries = [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1",
             "name": "Artifact", "input": {"file_path": "/x/page.html", "url": A + "AAAA1111"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
             "content": f"Published /x/page.html at {A}AAAA1111 (Version 2)"}]}},
        ]
        items = artifacts.from_turn(entries)
        self.assertEqual(items, [(A + "AAAA1111", "page.html")])
        self.assertFalse(artifacts.record(self.work, items))
        self.assertEqual(self.f.read_text("utf-8"), f"- [Real Title]({A}AAAA1111)\n")
        artifacts.record(self.work, [(A + "BBBB2222", items[0][1])])
        self.assertIn(f"- [page.html]({A}BBBB2222)", self.f.read_text("utf-8"))

    def test_message_mention_of_archived_link_is_skipped(self):
        artifacts.record(self.work, [(A + "AAAA1111", "One")])
        artifacts.mark_archived(self.work, "s1")
        before = self.f.read_bytes()
        self.assertFalse(artifacts.record(self.work, [(A + "AAAA1111", None)]))
        self.assertEqual(self.f.read_bytes(), before)
        self.assertTrue(artifacts.record(self.work, [(A + "AAAA1111", "One again")]))
        self.assertTrue(self.f.read_text("utf-8").endswith(f"- [One again]({A}AAAA1111)\n"))

    def test_creates_dir_and_file(self):
        self.assertTrue(artifacts.record(self.work, [(A + "AAAA1111", "One")]))
        self.assertEqual(self.f.read_bytes(), f"- [One]({A}AAAA1111)\n".encode())

    def test_dedupe_and_title_update_in_place(self):
        artifacts.record(self.work, [(A + "AAAA1111", "One"), (A + "BBBB2222", "Two")])
        self.assertTrue(artifacts.record(self.work, [(A + "AAAA1111", "One v2"), (A + "CCCC3333", "Three")]))
        self.assertEqual(self.f.read_text().splitlines(), [
            f"- [One v2]({A}AAAA1111)", f"- [Two]({A}BBBB2222)", f"- [Three]({A}CCCC3333)"])

    def test_no_write_when_unchanged(self):
        artifacts.record(self.work, [(A + "AAAA1111", "One")])
        before = self.f.stat().st_mtime_ns
        self.assertFalse(artifacts.record(self.work, [(A + "AAAA1111", "One"), (A + "AAAA1111", None)]))
        self.assertEqual(self.f.stat().st_mtime_ns, before)

    def test_untitled_keeps_existing_else_segment(self):
        artifacts.record(self.work, [(A + "AAAA1111", "One")])
        artifacts.record(self.work, [(A + "AAAA1111", None), (A + "BBBB2222", None)])
        self.assertEqual(self.f.read_text().splitlines(), [f"- [One]({A}AAAA1111)", f"- [BBBB2222]({A}BBBB2222)"])

    def test_sanitize_title(self):
        artifacts.record(self.work, [(A + "AAAA1111", "a\nb [x]  " + "z" * 300)])
        line = self.f.read_text().splitlines()[0]
        self.assertTrue(line.startswith(f"- [a b (x) zzz"), line)
        self.assertLessEqual(len(line), len(f"- []({A}AAAA1111)") + 200)
        self.assertEqual(len(self.f.read_text().splitlines()), 1)

    def test_segments_only_current_segment_dedupes(self):
        artifacts.record(self.work, [(A + "AAAA1111", "One")])
        artifacts.mark_archived(self.work, "s1")
        self.assertEqual(artifacts.segment_text(self.f.read_text()), "")
        self.assertTrue(artifacts.record(self.work, [(A + "AAAA1111", "One again"), (A + "BBBB2222", "Two")]))
        self.assertEqual(self.f.read_text().splitlines(), [
            f"- [One]({A}AAAA1111)", "<!-- archived: s1 -->",
            f"- [One again]({A}AAAA1111)", f"- [Two]({A}BBBB2222)"])
        self.assertEqual(artifacts.segment_text(self.f.read_text()),
                         f"- [One again]({A}AAAA1111)\n- [Two]({A}BBBB2222)\n")

    def test_merge_text(self):
        old = f"- [One]({A}AAAA1111)\n- [Two]({A}BBBB2222)\n"
        new = f"- [Two v2]({A}BBBB2222)\n- [Three]({A}CCCC3333)\n"
        self.assertEqual(artifacts.merge_text(old, new),
                         f"- [One]({A}AAAA1111)\n- [Two v2]({A}BBBB2222)\n- [Three]({A}CCCC3333)\n")

    def test_no_tmp_left_and_invalid_url_ignored(self):
        artifacts.record(self.work, [("https://example.com/x", "Bad"), (A + "AAAA1111", "One")])
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["ARTIFACTS.md"])
        self.assertNotIn("example.com", self.f.read_text())


class StopCaptureTests(GateBase):
    def setUp(self):
        super().setUp()
        self.work = self.proj / ".claude-work" / "current"
        self.tr.write_bytes(FIXTURE.read_bytes())

    def stop(self, **kw):
        ev = {"session_id": "s1", "hook_event_name": "Stop", "transcript_path": str(self.tr),
              "cwd": str(self.proj), **kw}
        r = run_gate(ev, self.home, cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.decode().strip()

    def lines(self):
        f = self.work / "ARTIFACTS.md"
        return f.read_text("utf-8").splitlines() if f.is_file() else None

    def test_stop_records_and_prints_nothing(self):
        out = self.stop(last_assistant_message=f"Open {A}MSGONLYMSG01 and "
                                               f"https://claude.ai/code/artifact/{WASH_ID}")
        self.assertEqual(out, "")
        self.assertEqual(self.lines(), [
            f"- [Wash Lab v2]({A}WASHWASHWASH1)", f"- [plain.html]({A}PLAINPLAIN001)",
            f"- [MSGONLYMSG01]({A}MSGONLYMSG01)"])

    def test_runs_when_stop_hook_active(self):
        self.assertEqual(self.stop(stop_hook_active=True), "")
        self.assertEqual(len(self.lines()), 2)

    def test_skipped_for_subagent(self):
        self.stop(agent_id="a1")
        self.assertIsNone(self.lines())

    def test_switch_off(self):
        self.config(WINDOW_OFF)
        self.stop()
        self.assertIsNone(self.lines())
        self.assertFalse(self.work.exists())

    def test_nothing_published_creates_nothing(self):
        self.tr.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        self.stop(last_assistant_message="no links")
        self.assertFalse(self.work.exists())

    def test_through_handle(self):
        import paths
        out = gate.handle({"session_id": "s1", "hook_event_name": "Stop",
                           "transcript_path": str(self.tr), "cwd": str(self.proj)})
        self.assertEqual(out, "")
        self.assertEqual(len(self.lines()), 2)
        self.assertTrue(paths.settings()["extract_artifacts"])


WINDOW_OFF = "[nudge]\ncontext_window = 300000\n[extract]\nartifacts = false\n"

if __name__ == "__main__":
    unittest.main()
