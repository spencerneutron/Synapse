"""Tests for tools/emission-stats.py."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent.parent / "tools" / "emission-stats.py"
_spec = importlib.util.spec_from_file_location("emission_stats", TOOL)
es = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(es)

SECRET = "PLANTED-SECRET-xyz"
SKILL_PATH = r"C:\\Users\\x\\.claude\\plugins\\cache\\synapse\\synapse\\2.6.0\\skills"


def user(text, side=False):
    return {"type": "user", "isSidechain": side, "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t", "content": SECRET}]}}


def asst(mid, model="model-a", load_id=None, side=False, skill="synapse:emission-contract"):
    content = [{"type": "text", "text": SECRET}]
    if load_id:
        content.append({"type": "tool_use", "id": load_id, "name": "Skill", "input": {"skill": skill}})
    return {"type": "assistant", "isSidechain": side,
            "message": {"id": mid, "model": model, "role": "assistant", "content": content}}


def stop(output=False):
    return {"type": "system", "subtype": "stop_hook_summary", "isSidechain": False, "hasOutput": output}


FIXTURE = [
    user("hello " + SKILL_PATH),                      # turn 1: user, load
    asst("m1", load_id="L1"),
    tool_result(),
    asst("m1b", load_id="L1"),                        # same tool_use id again
    {"type": "assistant", "isSidechain": False, "message": asst("m1c", load_id="L1")["message"],
     "subtype": "api-request-blob"},                  # duplicate in another entry
    stop(output=True),
    user("<command-name>/foo</command-name>"),        # turn 2: slash, no load
    asst("m2", model="model-b"),
    stop(),
    user("<task-notification>done</task-notification>"),  # turn 3: notification, load
    asst("m3", load_id="L2"),
    stop(),
    user("side prompt", side=True),                   # sidechain: ignored
    asst("s1", model="model-z", load_id="L3", side=True),
    user("<bash-input>ls</bash-input>"),              # turn 4: user (shell input)
    asst("m4"),
    stop(),
    {"type": "system", "subtype": "compact_boundary", "isSidechain": False},
]


def write(tmp, entries, name="session.jsonl"):
    p = Path(tmp) / name
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\nnot json\n", encoding="utf-8")
    return p


class EmissionStatsTest(unittest.TestCase):
    def test_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = es.analyze(write(tmp, FIXTURE))
        self.assertEqual(r["file"], "session.jsonl")
        self.assertEqual(r["turns"], 4)
        self.assertEqual(r["blocks"], 1)
        self.assertEqual(r["loads"], 2)
        self.assertEqual(r["compactions"], 1)
        self.assertEqual(r["versions"], ["2.6.0"])
        self.assertEqual(r["models"], ["model-a", "model-b"])
        o = r["origins"]
        self.assertEqual([o[k]["turns"] for k in es.ORIGINS], [2, 1, 1])
        self.assertEqual(o["user"]["load_turns"], [1])
        self.assertEqual(o["notification"]["load_turns"], [3])
        self.assertEqual(o["slash"]["loads"], 0)

    def test_render_has_no_message_text_or_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, FIXTURE)
            out = es.render([es.analyze(p), es.analyze(p)])
        self.assertNotIn(SECRET, out)
        self.assertNotIn(tmp, out)
        self.assertIn("TOTAL", out)

    def test_cli_json_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, FIXTURE)
            proc = subprocess.run([sys.executable, str(TOOL), str(p), str(Path(tmp) / "nope.jsonl"), "--json"],
                                  capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["loads"], 2)
        self.assertNotIn(SECRET, proc.stdout)


if __name__ == "__main__":
    unittest.main()
