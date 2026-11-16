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
        self.assertIn("brief for a role", r["additionalContext"])
        self.assertEqual(self.run_calls(5), [5])

    def prompt(self):
        return self.send({"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "x"})

    def test_digest_on_by_default(self):
        out = self.prompt()
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertIn("Stop hook checks your final message", out["additionalContext"])

    def test_digest_off_by_config(self):
        (self.home / "config.toml").write_text("[nudge]\ndigest = false\n")
        self.assertIsNone(self.prompt())
        (self.home / "config.toml").write_text("[nudge]\ndigest = true\n")
        self.assertIsNotNone(self.prompt())

    def test_digest_is_one_short_line(self):
        text = self.prompt()["additionalContext"]
        self.assertNotIn("\n", text)
        self.assertLess(len(text), 200)

    def test_digest_not_on_post_tool_use(self):
        for _ in range(5):
            out = self.call()
        self.assertNotIn("brief for a role, not work", out["additionalContext"])
        self.assertIsNone(self.call(tool="Read"))

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
                self.assertTrue("py.sh\" --optional " in h["command"])
                self.assertTrue(h["command"].endswith("nudge --hook"))
                self.assertEqual(h["timeout"], 10)
        for event in ("UserPromptSubmit", "SessionStart"):
            cmds = [h["command"] for g in hooks[event] for h in g["hooks"]]
            self.assertTrue(any(c.endswith("nudge --hook") for c in cmds), event)
            for g in hooks[event]:
                for h in g["hooks"]:
                    if h["command"].endswith("nudge --hook"):
                        self.assertEqual(h["timeout"], 10)


def make_effort(proj, slug, status="active", resume=None, title="T"):
    """An effort folder under proj with effort.json; `resume` is EXECUTION.md's text."""
    d = Path(proj) / ".claude-work" / "efforts" / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "effort.json").write_text(json.dumps({"slug": slug, "title": title, "status": status}), "utf-8")
    (d / "PLAN.md").write_text("# Plan\n", "utf-8")
    if resume is not None:
        (d / "EXECUTION.md").write_text(resume, "utf-8")
    (Path(proj) / ".git").mkdir(exist_ok=True)
    return d


def bind_session(home, sid, proj, slug):
    st = Path(home) / "state"
    st.mkdir(parents=True, exist_ok=True)
    f = st / f"effort-{sid}.json"
    f.write_text(json.dumps({"root": os.path.abspath(str(proj)), "slug": slug, "time": "x"}), "utf-8")
    return f


def write_handoff(home, proj, slug, frm="old", ago=1.0):
    import hashlib
    h = hashlib.sha256(os.path.normcase(str(Path(proj).resolve())).encode("utf-8")).hexdigest()[:16]
    st = Path(home) / "state"
    st.mkdir(parents=True, exist_ok=True)
    f = st / f"effort-handoff-{h}-{frm}.json"
    f.write_text(json.dumps({"slug": slug, "from": frm, "time": time.time() - ago}), "utf-8")
    return f


class EffortNudgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.proj = self.dir / "proj"
        self.proj.mkdir()

    def send(self, **ev):
        r = run(ev, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, b"")
        text = r.stdout.decode().strip()
        return json.loads(text)["hookSpecificOutput"]["additionalContext"] if text else ""

    def start(self, source="startup", sid="s1"):
        return self.send(session_id=sid, hook_event_name="SessionStart", source=source, cwd=str(self.proj))

    def post(self, path, sid="s1", tool="Edit", **extra):
        return self.send(session_id=sid, hook_event_name="PostToolUse", tool_name=tool,
                         tool_input={"file_path": str(path)}, cwd=str(self.proj), **extra)

    def bound(self, sid="s1"):
        f = self.home / "state" / f"effort-{sid}.json"
        return json.loads(f.read_text("utf-8"))["slug"] if f.is_file() else None

    def test_index_printed_on_every_source(self):
        make_effort(self.proj, "alpha")
        for source in ("startup", "resume", "clear", "compact"):
            self.assertIn("Synapse efforts in this project: 1 open", self.start(source))

    def test_nothing_new_without_efforts(self):
        (self.proj / ".claude-work" / "current").mkdir(parents=True)
        self.assertEqual(self.start("startup"), "")
        self.assertEqual(self.start("clear"), "")

    def test_index_before_pointer(self):
        make_effort(self.proj, "alpha", resume="# E\n## Resume\nnext\n")
        text = self.start("compact")
        self.assertTrue(text.startswith("Synapse efforts in this project"), text)
        self.assertIn("\nSynapse: efforts with a recorded checkpoint: alpha (", text)
        self.assertLess(text.index("Synapse efforts in"), text.index("recorded checkpoint"))

    def test_handoff_claimed_on_clear(self):
        make_effort(self.proj, "alpha", resume="# E\n## Resume\nnext\n")
        make_effort(self.proj, "beta", resume="# E\n## Resume\nnext\n")
        h = write_handoff(self.home, self.proj, "alpha")
        text = self.start("clear", sid="new")
        self.assertEqual(self.bound("new"), "alpha")
        self.assertFalse(h.exists())
        self.assertIn("work in progress on effort 'alpha' is recorded in "
                      ".claude-work/efforts/alpha/EXECUTION.md", text)
        self.assertIn("This session is on alpha", text)

    def test_no_claim_on_startup(self):
        make_effort(self.proj, "alpha")
        h = write_handoff(self.home, self.proj, "alpha")
        self.start("startup", sid="new")
        self.assertIsNone(self.bound("new"))
        self.assertTrue(h.exists())

    def test_no_claim_when_already_bound(self):
        make_effort(self.proj, "alpha")
        make_effort(self.proj, "beta")
        bind_session(self.home, "new", self.proj, "beta")
        h = write_handoff(self.home, self.proj, "alpha")
        self.start("clear", sid="new")
        self.assertEqual(self.bound("new"), "beta")
        self.assertTrue(h.exists())

    def test_prune_bindings_and_handoffs(self):
        make_effort(self.proj, "alpha")
        old_t = time.time() - 8 * 24 * 3600
        old = bind_session(self.home, "other", self.proj, "alpha")
        own = bind_session(self.home, "s1", self.proj, "alpha")
        fresh = bind_session(self.home, "fresh", self.proj, "alpha")
        for f in (old, own):
            os.utime(f, (old_t, old_t))
        old_h = write_handoff(self.home, self.proj, "alpha", frm="x", ago=3 * 24 * 3600)
        os.utime(old_h, (time.time() - 2 * 24 * 3600,) * 2)
        new_h = write_handoff(self.home, self.proj, "alpha", frm="y", ago=3600)
        self.start("startup")
        self.assertFalse(old.exists())
        self.assertFalse(old_h.exists())
        self.assertTrue(own.exists() and fresh.exists() and new_h.exists())

    def test_prompt_touches_binding_and_notice_once(self):
        d = make_effort(self.proj, "alpha")
        f = bind_session(self.home, "s1", self.proj, "alpha")
        t = time.time() - 3600
        os.utime(f, (t, t))
        prompt = dict(session_id="s1", hook_event_name="UserPromptSubmit", cwd=str(self.proj))
        self.assertNotIn("no longer open", self.send(**prompt))
        self.assertGreater(f.stat().st_mtime, t + 1800)
        (d / "effort.json").write_text(json.dumps({"slug": "alpha", "status": "done", "archive_id": "A1"}))
        out = self.send(**prompt)
        self.assertIn("effort 'alpha' that this session was on is closed (done, archive A1)", out)
        self.assertNotIn("effort 'alpha' that this session", self.send(**prompt))

    def test_post_tool_binds_unbound_session(self):
        d = make_effort(self.proj, "alpha")
        self.post(d / "PLAN.md")
        self.assertEqual(self.bound(), "alpha")

    def test_post_tool_binds_when_dispatch_line_is_exempt_and_failure_does_not(self):
        d = make_effort(self.proj, "alpha")
        self.send(session_id="s1", hook_event_name="PostToolUseFailure", tool_name="Edit",
                  tool_input={"file_path": str(d / "PLAN.md")}, cwd=str(self.proj))
        self.assertIsNone(self.bound())
        self.post(d / "EXECUTION.md")
        self.assertEqual(self.bound(), "alpha")

    def test_post_tool_does_not_rebind(self):
        make_effort(self.proj, "alpha")
        d = make_effort(self.proj, "beta")
        bind_session(self.home, "s1", self.proj, "alpha")
        self.post(d / "PLAN.md")
        self.assertEqual(self.bound(), "alpha")

    def test_post_tool_ignores_subagent_and_closed_paths(self):
        d = make_effort(self.proj, "alpha")
        self.post(d / "PLAN.md", agent_id="a1")
        self.assertIsNone(self.bound())
        closed = d.parent / "_closed" / "2026-01-01-0000-alpha"
        closed.mkdir(parents=True)
        self.post(closed / "PLAN.md")
        self.assertIsNone(self.bound())

    def test_effort_module_not_imported_without_efforts(self):
        (self.proj / ".claude-work" / "current").mkdir(parents=True)
        prog = (
            "import sys, json\n"
            f"sys.path.insert(0, {str(LIB)!r})\n"
            "import nudge\n"
            "for ev in json.loads(sys.argv[1]):\n"
            "    nudge.handle(ev)\n"
            "print('effort' in sys.modules)\n")
        proj = str(self.proj)
        evs = [
            dict(session_id="s1", hook_event_name="SessionStart", source="startup", cwd=proj),
            dict(session_id="s1", hook_event_name="UserPromptSubmit", cwd=proj),
            dict(session_id="s1", hook_event_name="PostToolUse", tool_name="Edit",
                 tool_input={"file_path": proj + "/a.py"}, cwd=proj),
        ]
        r = subprocess.run([sys.executable, "-c", prog, json.dumps(evs)], capture_output=True,
                           env=dict(os.environ, SYNAPSE_HOME=str(self.home), SYNAPSE_OPTIONAL="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.decode().strip().splitlines()[-1], "False", r.stdout)


if __name__ == "__main__":
    unittest.main()
