"""Tests for tools/context-cost.py."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "context-cost.py"
_spec = importlib.util.spec_from_file_location("context_cost", TOOL)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

SECRET = "PLANTED-SECRET-xyz"


def asst(mid, ctx_in=0, read=0, write=0, out=0, model="claude-test-1", ts="2026-01-01T00:00:00Z",
         split=None, content=None):
    usage = {"input_tokens": ctx_in, "cache_read_input_tokens": read,
             "cache_creation_input_tokens": write, "output_tokens": out}
    if split:
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": split[0],
                                   "ephemeral_5m_input_tokens": split[1]}
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "usage": usage,
                        "content": content or [{"type": "text", "text": SECRET}]}}


def write(path, entries, extra_raw=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")
        for raw in extra_raw:
            fh.write(raw + "\n")


class ContextCostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "projects" / "proj"
        self.main = self.dir / "sess.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_shared_message_id_counted_once(self):
        write(self.main, [asst("m1", 10, 100, 0, 5)] * 3 + [asst("m2", 10, 200, 0, 5)])
        r = cc.analyze(self.main)
        self.assertEqual(r["main"]["requests"], 2)
        self.assertEqual(r["main"]["cache_reads"], 300)

    def test_malformed_and_other_lines_skipped(self):
        write(self.main, [
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"id": "x"}},
            {"type": "assistant", "message": "odd"},
            {"type": "assistant", "message": {"id": "y", "usage": {"input_tokens": "a"}}},
            asst("ok", 5, 0, 0, 1),
        ], extra_raw=["not json", "[1,2]", ""])
        r = cc.analyze(self.main)
        self.assertEqual(r["main"]["requests"], 2)  # "y" parses with zeros
        self.assertEqual(r["main"]["mean_context"], 2)

    def test_missing_file_does_not_crash(self):
        r = cc.analyze(self.dir / "nope.jsonl")
        self.assertEqual(r["all"]["requests"], 0)

    def test_cache_creation_split(self):
        write(self.main, [asst("m1", 0, 0, 1000, 0, split=(400, 600)),
                          asst("m2", 0, 0, 50, 0)])
        r = cc.analyze(self.main)
        self.assertEqual(r["main"]["cache_write_1h"], 400)
        self.assertEqual(r["main"]["cache_write_5m"], 650)

    def test_main_vs_subagent_share(self):
        write(self.main, [asst("m1", 0, 100, 0, 10)])
        write(self.dir / "sess" / "subagents" / "a.jsonl", [asst("s1", 0, 200, 0, 10), asst("s2", 0, 100, 0, 10)])
        write(self.dir / "sess" / "subagents" / "b.jsonl", [asst("s1", 0, 100, 0, 10)])
        r = cc.analyze(self.main)
        self.assertEqual(r["subagent_files"], 2)
        self.assertEqual(r["subagent"]["requests"], 3)
        self.assertEqual(r["all"]["cache_reads"], 500)
        self.assertEqual(r["main_share_pct"]["cache_reads"], 20.0)

    def test_compaction_and_checkpoints(self):
        write(self.main, [
            {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-01-01T00:00:00Z",
             "compactMetadata": {"trigger": "auto", "preTokens": 900, "postTokens": 100}},
            {"type": "system", "subtype": "other"},
            asst("m1", content=[{"type": "tool_use", "name": "Skill", "input": {"skill": "synapse:checkpoint"}}]),
            {"type": "user", "message": {"content": "run synapse:checkpoint now"}},
        ])
        r = cc.analyze(self.main)
        self.assertEqual(r["checkpoints"], 2)
        self.assertEqual(len(r["compactions"]), 1)
        c = r["compactions"][0]
        self.assertEqual((c["trigger"], c["pre_tokens"], c["post_tokens"]), ("auto", 900, 100))

    def test_mean_and_p90_context(self):
        write(self.main, [asst(f"m{i}", i * 10, 0, 0, 0) for i in range(1, 11)])  # 10..100
        r = cc.analyze(self.main)
        self.assertEqual(r["main"]["mean_context"], 55)
        self.assertEqual(r["main"]["p90_context"], 90)

    def test_cost_arithmetic(self):
        # input 100, read 1000, write 400 (1h 100, 5m 300), output 10
        write(self.main, [asst("m1", 100, 1000, 400, 10, split=(100, 300))])
        r = cc.analyze(self.main)["main"]
        self.assertAlmostEqual(r["cost_base_equiv"], 100 + 100 + 500 + 50)  # 750
        self.assertAlmostEqual(r["cost_base_equiv_1h2x"], 100 + 100 + 375 + 200 + 50)  # 825

    def test_subprocess_numbers_only(self):
        write(self.main, [asst("m1", 10, 100, 20, 5, model="claude-test-1")])
        write(self.dir / "sess" / "subagents" / "a.jsonl", [asst("s1", 0, 50, 0, 1)])
        for flags in ([], ["--json"]):
            p = subprocess.run([sys.executable, str(TOOL), str(self.main), *flags],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertNotIn(SECRET, p.stdout)
            self.assertNotIn(self.tmp.name, p.stdout)
            self.assertIn("claude-test-1", p.stdout)
        self.assertIn("main share %", subprocess.run(
            [sys.executable, str(TOOL), str(self.main)], capture_output=True, text=True).stdout)


if __name__ == "__main__":
    unittest.main()
