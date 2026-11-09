import json
import subprocess
import sys
import unittest
from datetime import datetime, timedelta

from helpers import LIB, ROOT  # noqa: F401  (sets up sys.path and SYNAPSE_HOME)
from test_continuation import Base, usage_entry, write
from test_hooks import BASH
from test_nudge import CLI, PY_SH

import checkpoint
import gate
import os

REASON_5 = ("Synapse gate: 5 hands-on calls in this step at about 270k context (each call here "
            "costs about 27k base-equivalent). Brief the rest of this step to synapse:implementer "
            "(goal, files, failing command, done condition, attempt limit) or synapse:scout / "
            "synapse:researcher for searches, then read the report. This gate lifts after a "
            "dispatch or on the next prompt.")
CKPT = ("Synapse: the context is about {} tokens. Run /synapse:checkpoint now (rewrite ## Resume "
        "in EXECUTION.md, append to NOTES.md, `synapse checkpoint --stamp`), then finish your "
        "message.")
WINDOW = "[nudge]\ncontext_window = 300000\n"
BIG = 270400


def run_gate(stdin, home, cwd=None, **env):
    data = stdin if isinstance(stdin, bytes) else json.dumps(stdin).encode()
    e = dict(os.environ, SYNAPSE_HOME=str(home), SYNAPSE_OPTIONAL="1", **env)
    cmd = [BASH, str(PY_SH), str(CLI), "gate", "--hook"] if BASH else \
        [sys.executable, str(CLI), "gate", "--hook"]
    return subprocess.run(cmd, input=data, capture_output=True, env=e, cwd=cwd)


class GateBase(Base):
    def setUp(self):
        super().setUp()
        self.proj = self.dir / "proj"
        self.proj.mkdir()
        self.config(WINDOW)

    def count_file(self, sid="s1"):
        return self.home / "state" / f"nudge-{sid}.count"

    def set_count(self, n, sid="s1"):
        f = self.count_file(sid)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"." * n)

    def gate(self, event="PreToolUse", ctx=BIG, tool="Bash", ti=None, sid="s1", cwd=True, **extra):
        if ctx is not None:
            write(self.tr, [usage_entry(ctx)])
        ev = {"session_id": sid, "hook_event_name": event, "transcript_path": str(self.tr), **extra}
        if event == "PreToolUse":
            ev.update(tool_name=tool, tool_input={"command": "make"} if ti is None else ti)
        if cwd is True:
            ev["cwd"] = str(self.proj)
        r = run_gate(ev, self.home, cwd=self.dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode().strip()
        return json.loads(text) if text else None

    def denied(self, **kw):
        out = self.gate(**kw)
        if out is not None:
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        return out is not None

    def nudge(self, event, ctx=BIG, tool="Bash", sid="s1", ti=None):
        write(self.tr, [usage_entry(ctx)])
        return self.send({"session_id": sid, "hook_event_name": event, "tool_name": tool,
                          "tool_input": {"command": "make"} if ti is None else ti,
                          "transcript_path": str(self.tr)})


class PreToolTests(GateBase):
    def test_threshold_crossings(self):
        for n in range(5):
            self.set_count(n)
            self.assertFalse(self.denied(), n)
        self.set_count(5)
        self.assertTrue(self.denied())
        self.assertFalse(self.denied())   # the retry
        for n in (6, 7, 8, 9):
            self.set_count(n)
            self.assertFalse(self.denied(), n)
        for n in (10, 20):
            self.set_count(n)
            self.assertTrue(self.denied(), n)
            self.assertFalse(self.denied(), n)

    def test_dispatch_and_prompt_reset_and_rearm(self):
        for event, tool in (("PostToolUse", "Agent"), ("UserPromptSubmit", "")):
            with self.subTest(event=event):
                self.setUp()
                self.set_count(5)
                self.assertTrue(self.denied())
                self.assertTrue(list((self.home / "state").glob("context-s1.gate.*")))
                self.nudge(event, tool=tool)
                self.assertFalse(self.count_file().exists())
                self.assertFalse(list((self.home / "state").glob("context-s1.gate.*")))
                self.set_count(4)
                self.assertFalse(self.denied())
                self.set_count(5)
                self.assertTrue(self.denied())

    def test_dispatch_resets_through_real_counting(self):
        for _ in range(5):
            self.nudge("PostToolUse", ctx=10000)
        self.assertEqual(self.count_file().stat().st_size, 5)
        self.assertTrue(self.denied())

    def test_min_context(self):
        self.set_count(5)
        self.assertFalse(self.denied(ctx=100000))
        self.config(WINDOW + "[gate]\nmin_context = 0\n")
        self.assertTrue(self.denied(ctx=100000))
        self.config(WINDOW)
        self.setUp()
        self.set_count(5)
        self.assertTrue(self.denied(ctx=160000))

    def test_nudge_line_below_min_context_only(self):
        for _ in range(5):
            out = self.nudge("PostToolUse", ctx=100000)
        self.assertIn("hands-on calls in a row", out["additionalContext"])
        self.setUp()
        for _ in range(5):
            out = self.nudge("PostToolUse", ctx=160000)
        self.assertIsNone(out)

    def test_switches_off(self):
        self.set_count(5)
        self.config(WINDOW + "[gate]\nenabled = false\n")
        self.assertFalse(self.denied())
        self.config(WINDOW + "[nudge]\ncalls = 0\n")   # context_window overridden below
        self.config("[nudge]\ncontext_window = 300000\ncalls = 0\n")
        self.assertFalse(self.denied())

    def test_exemptions_never_denied_and_do_not_consume(self):
        self.set_count(5)
        heredoc = 'git add -A && git commit -m "$(cat <<\'EOF\'\nmsg; with && inside\nEOF\n)"'
        exempt = [("Bash", {"command": "synapse where"}),
                  ("Edit", {"file_path": "/x/.claude-work/current/PLAN.md"}),
                  ("Bash", {"command": "git commit -m x"}),
                  ("Bash", {"command": heredoc}),
                  ("Bash", {"command": "git -C /x push"}),
                  ("Bash", {"command": "cd /x && git push origin b"}),
                  ("Bash", {"command": "gh pr create --title t"})]
        for tool, ti in exempt:
            self.assertFalse(self.denied(tool=tool, ti=ti), ti)
        self.assertTrue(self.denied())   # threshold still due

    def test_chained_commit_is_not_exempt(self):
        self.set_count(5)
        self.assertTrue(self.denied(ti={"command": "pytest && git commit -m x"}))

    def test_shipping(self):
        for cmd in ("git commit -m x", "git push", "git -C /x push", "cd /x && git push origin b",
                    "gh pr create", "git add . && git commit -m x", "git -C /r add a; git commit"):
            self.assertTrue(gate.shipping(cmd), cmd)
        for cmd in ("pytest && git commit -m x", "git status", "make", "echo git commit",
                    "git log", "gh issue list"):
            self.assertFalse(gate.shipping(cmd), cmd)

    def test_reason_and_shape(self):
        self.set_count(5)
        out = self.gate()
        self.assertEqual(out, {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": REASON_5}})

    def test_other_tools_and_subagents_and_garbage(self):
        self.set_count(5)
        for tool in ("Agent", "Task", "Read", "Grep"):
            self.assertIsNone(self.gate(tool=tool, ti={}), tool)
        self.assertIsNone(self.gate(agent_id="a1"))
        for junk in (b"", b"not json", b"[1,2]", b"null"):
            r = run_gate(junk, self.home, cwd=self.dir)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, b""), junk)
        self.assertTrue(self.denied())   # nothing above consumed the threshold

    def test_project_override(self):
        self.config("[nudge]\ncontext_window = 300000\n")
        (self.proj / ".synapse.toml").write_text("[gate]\nmin_context = 0\n")
        self.set_count(5)
        self.assertFalse(self.denied(ctx=10000, cwd=False))
        self.assertTrue(self.denied(ctx=10000))


class StopTests(GateBase):
    def setUp(self):
        super().setUp()
        self.config("[nudge]\ncontext_window = 100000\n")
        self.work = self.proj / ".claude-work" / "current"

    def stop(self, ctx, **kw):
        return self.gate(event="Stop", ctx=ctx, **kw)

    def block(self, ctx):
        return {"decision": "block", "reason": CKPT.format(f"{round(ctx / 1000)}k")}

    def state(self):
        f = self.home / "state" / "context-s1.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def resume(self, stamp=True, ago=None):
        self.work.mkdir(parents=True, exist_ok=True)
        s = ""
        if stamp:
            when = datetime.now() - (ago or timedelta())
            s = f"Checkpoint written: {checkpoint.stamp_text(when)}\n"
        (self.work / "EXECUTION.md").write_text(f"# Exec\n\n## Resume\n{s}Next: x\n")

    def test_levels_once_each(self):
        self.work.mkdir(parents=True)
        self.assertIsNone(self.stop(50000))
        self.assertEqual(self.stop(65000), self.block(65000))
        self.assertIsNone(self.stop(70000))
        self.assertEqual(self.stop(92000), self.block(92000))
        self.assertIsNone(self.stop(95000))

    def test_stop_hook_active(self):
        self.work.mkdir(parents=True)
        self.assertIsNone(self.stop(65000, stop_hook_active=True))
        self.assertEqual(self.stop(65000), self.block(65000))   # not consumed

    def test_without_work_dir(self):
        self.assertIsNone(self.stop(65000))
        self.assertEqual(self.stop(92000), self.block(92000))

    def test_resume_written_after_crossing(self):
        self.work.mkdir(parents=True)
        self.nudge("PostToolUse", ctx=65000, ti={"command": "make"})
        if not (self.state().get("crossed") or {}).get("low"):
            (self.home / "state").mkdir(exist_ok=True)
            (self.home / "state" / "context-s1.json").write_text(
                json.dumps({"crossed": {"low": datetime.now().timestamp() - 5}}))
        self.resume()
        self.assertIsNone(self.stop(66000))

    def test_resume_older_than_crossing(self):
        self.work.mkdir(parents=True)
        self.resume(ago=timedelta(hours=2))
        self.assertEqual(self.stop(65000), self.block(65000))

    def test_unstamped_resume_uses_mtime(self):
        self.resume(stamp=False)
        (self.home / "state").mkdir(exist_ok=True)
        (self.home / "state" / "context-s1.json").write_text(
            json.dumps({"crossed": {"low": datetime.now().timestamp() - 600}}))
        self.assertIsNone(self.stop(65000))

    def test_dropping_below_clears_crossing(self):
        self.work.mkdir(parents=True)
        self.assertEqual(self.stop(65000), self.block(65000))
        self.assertTrue(self.state().get("crossed"))
        self.assertIsNone(self.stop(50000))
        self.assertFalse(self.state().get("crossed"))

    def test_switches_off(self):
        self.work.mkdir(parents=True)
        self.config("[nudge]\ncontext_window = 100000\n[gate]\ncheckpoint = false\n")
        self.assertIsNone(self.stop(65000))
        self.assertIsNone(self.stop(95000))
        self.config("[nudge]\ncontext_window = 0\n")
        self.assertIsNone(self.stop(65000))


if __name__ == "__main__":
    unittest.main()


WAIT = ("Synapse: a dispatched agent is still running. End this turn with one line naming what you are "
        "waiting for; the agent's report or the user's next message resumes you. Verify the report before "
        "calling the work done, and if the agent asked a question, answer it or relay it.")
RUNNING = [{"id": "a1", "type": "subagent", "status": "running", "agent_type": "synapse:implementer",
            "description": "fix loop"}]


class WaitTests(GateBase):
    """Stop: block once per prompt while background_tasks lists a running sub-agent."""

    def setUp(self):
        super().setUp()
        self.config("[nudge]\ncontext_window = 1000000\n")   # keep the checkpoint ask out of the way

    def stop(self, tasks, **kw):
        return self.gate(event="Stop", ctx=10000, background_tasks=tasks, **kw)

    def test_running_subagent_blocks_once_per_prompt(self):
        self.assertEqual(self.stop(RUNNING), {"decision": "block", "reason": WAIT})
        self.assertIsNone(self.stop(RUNNING))
        self.nudge("UserPromptSubmit", ctx=10000)        # a new prompt re-arms it
        self.assertEqual(self.stop(RUNNING), {"decision": "block", "reason": WAIT})

    def test_finished_shell_or_no_tasks_pass(self):
        self.assertIsNone(self.stop([dict(RUNNING[0], status="completed")]))
        self.assertIsNone(self.stop([{"id": "b1", "type": "shell", "status": "running",
                                      "command": "tail -f x"}]))
        self.assertIsNone(self.stop([]))
        self.assertIsNone(self.gate(event="Stop", ctx=10000))   # field absent
        self.assertIsNone(self.stop("garbage"))

    def test_stop_hook_active_and_switch(self):
        self.assertIsNone(self.stop(RUNNING, stop_hook_active=True))
        self.config("[nudge]\ncontext_window = 1000000\n[gate]\nwait_for_agents = false\n")
        self.assertIsNone(self.stop(RUNNING))

    def test_checkpoint_ask_comes_first(self):
        self.config("[nudge]\ncontext_window = 10000\n")   # 10k of 10k: the 90% ask is due
        out = self.stop(RUNNING)
        self.assertIn("/synapse:checkpoint", out["reason"])
