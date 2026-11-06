import json
import os
import subprocess
import sys
import tempfile
import time
import multiprocessing
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from helpers import LIB, ROOT

from test_hooks import BASH

PY_SH = ROOT / "lib" / "py.sh"
CLI = ROOT / "lib" / "synapse" / "cli.py"
MATCHER = "Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit|Agent|Task"


def run(stdin, home, **env):
    data = stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode()
    e = dict(os.environ, SYNAPSE_HOME=str(home), SYNAPSE_OPTIONAL="1", **env)
    cmd = [BASH, str(PY_SH), str(CLI), "nudge", "--hook"] if BASH else \
        [sys.executable, str(CLI), "nudge", "--hook"]
    return subprocess.run(cmd, input=data, capture_output=True, env=e)


def stress_worker(args):
    home, n = args
    os.environ["SYNAPSE_HOME"] = home
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    import nudge
    import paths
    return [nudge.count_call(paths, "stress") for _ in range(n)]


class NudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def call(self, tool="Bash", event="PostToolUse", sid="s1", **extra):
        stdin = {"session_id": sid, "hook_event_name": event, "tool_name": tool,
                 "tool_input": {}, **extra}
        return self.send(stdin)

    def send(self, stdin, **env):
        r = run(stdin, self.home, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode().strip()
        if not text:
            return None
        out = json.loads(text)
        self.assertEqual(set(out), {"hookSpecificOutput"})
        return out["hookSpecificOutput"]

    def run_calls(self, n, **kw):
        """Counts at which a nudge appeared over n calls."""
        return [i for i in range(1, n + 1) if self.call(**kw)]

    def state(self, sid="s1"):
        return self.home / "state" / f"nudge-{sid}.count"

    def test_nudges_at_5_10_20_only(self):
        self.assertEqual(self.run_calls(25), [5, 10, 20])

    def test_output_shape_for_both_events(self):
        for event in ("PostToolUse", "PostToolUseFailure"):
            with self.subTest(event=event):
                self.setUp()
                out = None
                for _ in range(5):
                    out = self.call(event=event)
                self.assertEqual(out["hookEventName"], event)
                self.assertIn("5 hands-on calls", out["additionalContext"])
                self.assertIn("synapse:implementer", out["additionalContext"])
                self.assertIn("synapse:scout", out["additionalContext"])
                self.assertEqual(set(out), {"hookEventName", "additionalContext"})

    def test_agent_call_resets(self):
        self.assertEqual(self.run_calls(4), [])
        self.assertIsNone(self.call(tool="Agent"))
        self.assertFalse(self.state().exists())
        self.assertEqual(self.run_calls(5), [5])
        self.call(tool="Task")
        self.assertFalse(self.state().exists())

    def test_user_prompt_resets(self):
        self.run_calls(4)
        r = self.send({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "x"})
        self.assertIsNone(r)
        self.assertEqual(self.run_calls(5), [5])

    def test_sub_agent_calls_are_ignored(self):
        for _ in range(7):
            self.assertIsNone(self.call(agent_id="a1"))
        self.assertFalse(self.state().exists())
        self.run_calls(2)
        self.assertEqual(self.state().stat().st_size, 2)
        self.call(tool="Agent", agent_id="a1")
        self.assertEqual(self.state().stat().st_size, 2)

    def test_other_tools_ignored(self):
        for tool in ("Read", "Grep", "Glob", "WebFetch"):
            self.assertIsNone(self.call(tool=tool))
        self.assertFalse(self.state().exists())

    def test_sessions_are_independent(self):
        self.run_calls(4, sid="a")
        self.assertEqual(self.run_calls(5, sid="b"), [5])
        self.assertIsNotNone(self.call(sid="a"))

    def test_custom_budget(self):
        (self.home / "config.toml").write_text("[nudge]\ncalls = 3\n")
        self.assertEqual(self.run_calls(13), [3, 6, 12])

    def test_zero_turns_it_off(self):
        (self.home / "config.toml").write_text("[nudge]\ncalls = 0\n")
        self.assertEqual(self.run_calls(10), [])
        self.assertFalse((self.home / "state").exists())

    def test_malformed_config(self):
        (self.home / "config.toml").write_text('[nudge]\ncalls = "x"\n')
        self.assertEqual(self.run_calls(6), [])
        (self.home / "config.toml").write_text("[nudge\n")
        self.assertEqual(self.run_calls(6), [])

    def test_bad_input(self):
        for stdin in (b"{not json", b"", b"[]", b"null", b"\xff\xfe", b"5",
                      {"hook_event_name": "PostToolUse", "tool_name": "Bash"},
                      {"session_id": "", "hook_event_name": "PostToolUse", "tool_name": "Bash"},
                      {"session_id": "!!!", "hook_event_name": "PostToolUse", "tool_name": "Bash"},
                      {"session_id": 5, "hook_event_name": "PostToolUse", "tool_name": "Bash"},
                      {"session_id": "s", "hook_event_name": "Stop"}):
            with self.subTest(stdin=stdin):
                self.assertIsNone(self.send(stdin))
        self.assertFalse((self.home / "state").exists())

    def test_without_hook_flag_prints_docstring(self):
        r = subprocess.run([sys.executable, str(CLI), "nudge"], capture_output=True,
                           env=dict(os.environ, SYNAPSE_HOME=str(self.home)))
        self.assertEqual(r.returncode, 0)
        self.assertIn("never block", r.stdout.decode())

    def test_unwritable_home(self):
        blocker = Path(self.tmp.name) / "file"
        blocker.write_text("x")
        self.home = blocker / "sub"
        self.assertEqual(self.run_calls(6), [])

    def test_session_start_prunes_old_counters(self):
        state = self.home / "state"
        state.mkdir()
        old, fresh, own = state / "nudge-old.count", state / "nudge-new.count", state / "nudge-s1.count"
        other = state / "hints-old.json"
        for f in (old, fresh, own, other):
            f.write_bytes(b"...")
        past = time.time() - 2 * 86400
        for f in (old, other):
            os.utime(f, (past, past))
        self.assertIsNone(self.send({"session_id": "s1", "hook_event_name": "SessionStart"}))
        self.assertFalse(old.exists())
        self.assertFalse(own.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(other.exists())

    def test_synapse_cli_calls_do_not_count(self):
        for _ in range(6):
            self.assertIsNone(self.call(tool_input={"command": "synapse vault create-note x"}))
        self.assertIsNone(self.call(tool="PowerShell", tool_input={"command": "  synapse"}))
        self.assertFalse(self.state().exists())
        self.assertIsNone(self.call(tool_input={"command": "synapsex y"}))
        self.assertEqual(self.state().stat().st_size, 1)

    def test_claude_work_edits_do_not_count(self):
        plan = os.path.join(self.tmp.name, "x", ".claude-work", "current", "EXECUTION.md")
        win = "C:\\x\\.claude-work\\current\\PLAN.md"
        for tool, key, path in (("Edit", "file_path", plan), ("Write", "file_path", win),
                                ("NotebookEdit", "notebook_path", plan)):
            self.assertIsNone(self.call(tool=tool, tool_input={key: path}))
        self.assertFalse(self.state().exists())
        self.call()
        self.assertEqual(self.state().stat().st_size, 1)
        self.call(tool="Edit", tool_input={"file_path": "/x/src/a.py"})
        self.assertEqual(self.state().stat().st_size, 2)

    def test_odd_tool_input_counts(self):
        for ti in (None, "str", [], 5):
            self.call(tool_input=ti)
        self.assertEqual(self.state().stat().st_size, 4)

    @unittest.skipIf(sys.platform == "win32",
                     "UCRT emulates O_APPEND as seek-then-write, so counts may race; a doubled or missed nudge is the worst case")
    def test_parallel_calls_count_exactly(self):
        with ThreadPoolExecutor(20) as ex:
            outs = list(ex.map(lambda _: self.call(), range(20)))
        self.assertEqual(self.state().stat().st_size, 20)
        self.assertEqual(len([o for o in outs if o]), 3)

    @unittest.skipIf(sys.platform == "win32", "UCRT emulates O_APPEND as seek-then-write")
    def test_stress_counts_are_unique(self):
        workers, per = 16, 500
        with multiprocessing.get_context("spawn").Pool(workers) as pool:
            got = pool.map(stress_worker, [(str(self.home), per)] * workers)
        counts = [c for g in got for c in g]
        self.assertEqual(sorted(counts), list(range(1, workers * per + 1)))
        self.assertEqual(self.state("stress").stat().st_size, workers * per)

    def test_hooks_json_registers_post_tool_events(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        for event in ("PostToolUse", "PostToolUseFailure"):
            with self.subTest(event=event):
                self.assertEqual(len(hooks[event]), 1)
                self.assertEqual(hooks[event][0]["matcher"], MATCHER)
                h = hooks[event][0]["hooks"][0]
                self.assertTrue(h["command"].startswith("SYNAPSE_OPTIONAL=1 "))
                self.assertTrue(h["command"].endswith("nudge --hook"))
                self.assertEqual(h["timeout"], 10)
        for event in ("UserPromptSubmit", "SessionStart"):
            cmds = [h["command"] for g in hooks[event] for h in g["hooks"]]
            self.assertTrue(any(c.endswith("nudge --hook") for c in cmds), event)
            for g in hooks[event]:
                for h in g["hooks"]:
                    if h["command"].endswith("nudge --hook"):
                        self.assertEqual(h["timeout"], 10)


if __name__ == "__main__":
    unittest.main()
