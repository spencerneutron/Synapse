import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from helpers import LIB  # noqa: F401  (sets up sys.path and SYNAPSE_HOME)
from test_nudge import run

import continuation

LINE_PAD = "x" * 900


def ts(ago_s=0):
    t = datetime.now(timezone.utc) - timedelta(seconds=ago_s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def usage_entry(ctx=100000, ago_s=0, ttl="1h", sidechain=False, **kw):
    cc = {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0}
    if ttl == "1h":
        cc["ephemeral_1h_input_tokens"] = 10
    elif ttl == "5m":
        cc["ephemeral_5m_input_tokens"] = 10
    usage = {"input_tokens": 1, "cache_read_input_tokens": ctx - 11,
             "cache_creation_input_tokens": 10, "cache_creation": cc}
    e = {"type": "assistant", "timestamp": ts(ago_s), "isSidechain": sidechain,
         "message": {"usage": usage}}
    e.update(kw)
    return json.dumps(e)


def write(path, lines):
    Path(path).write_text("\n".join(lines) + "\n", "utf-8")


DIGEST_START = "Synapse: a step over about five tool calls"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.tr = self.dir / "t.jsonl"

    def send(self, stdin):
        r = run(stdin, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = r.stdout.decode().strip()
        if not text:
            return None
        out = json.loads(text)
        self.assertEqual(set(out), {"hookSpecificOutput"})
        out = out["hookSpecificOutput"]
        if out.get("hookEventName") == "UserPromptSubmit":
            # the always-on prompt digest is tested in test_nudge; drop it here
            rest = [x for x in out["additionalContext"].split("\n") if not x.startswith(DIGEST_START)]
            if not rest:
                return None
            out = dict(out, additionalContext="\n".join(rest))
        return out

    def config(self, text):
        (self.home / "config.toml").write_text(text, "utf-8")

    def post(self, ctx, event="PostToolUse", tool="Bash", sid="s1", **extra):
        write(self.tr, [usage_entry(ctx)])
        return self.send({"session_id": sid, "hook_event_name": event, "tool_name": tool,
                          "tool_input": {}, "transcript_path": str(self.tr), **extra})


class TailReader(Base):
    def test_large_transcript(self):
        with open(self.tr, "wb") as f:
            filler = (json.dumps({"type": "user", "message": LINE_PAD}) + "\n").encode()
            for _ in range(50_000_000 // len(filler)):
                f.write(filler)
            f.write(b"not json at all\n")
            f.write((usage_entry(123456, ttl="5m") + "\n").encode())
            for _ in range(200):
                f.write(filler)
            f.write(b'{"type":"system"}\n{"broken\n')
        self.assertGreater(self.tr.stat().st_size, 50_000_000)
        u = continuation.last_usage(str(self.tr))
        self.assertEqual(u["context"], 123456)
        self.assertEqual(u["ttl"], "5m")
        self.assertIsNotNone(u["time"].tzinfo)

    def test_beyond_cap_is_none(self):
        filler = json.dumps({"type": "user", "message": LINE_PAD})
        write(self.tr, [usage_entry()] + [filler] * (3 * 1024 * 1024 // len(filler)))
        self.assertIsNone(continuation.last_usage(str(self.tr)))

    def test_skips_sidechain_zero_and_non_assistant(self):
        zero = json.dumps({"type": "assistant", "timestamp": ts(),
                           "message": {"usage": {"input_tokens": 0}}})
        write(self.tr, [usage_entry(50000), usage_entry(90000, sidechain=True), zero,
                        json.dumps({"type": "assistant", "message": {"usage": {}}}),
                        json.dumps({"type": "user", "message": {"usage": {"input_tokens": 9}}})])
        self.assertEqual(continuation.last_usage(str(self.tr))["context"], 50000)

    def test_ttl(self):
        write(self.tr, [usage_entry(ttl="1h")])
        self.assertEqual(continuation.last_usage(str(self.tr))["ttl"], "1h")
        write(self.tr, [usage_entry(ttl="5m")])
        self.assertEqual(continuation.last_usage(str(self.tr))["ttl"], "5m")
        write(self.tr, [usage_entry(ttl="5m"), usage_entry(ttl=None)])
        u = continuation.last_usage(str(self.tr))
        self.assertEqual(u["ttl"], "5m")
        write(self.tr, [usage_entry(ttl=None)])
        self.assertIsNone(continuation.last_usage(str(self.tr))["ttl"])

    def test_bad_paths(self):
        for p in (None, 5, str(self.dir), str(self.dir / "missing")):
            self.assertIsNone(continuation.last_usage(p))
        self.tr.write_bytes(b"\xff\xfe{\n[1]\n\n")
        self.assertIsNone(continuation.last_usage(str(self.tr)))

    def test_fmt_age(self):
        f = continuation.fmt_age
        self.assertEqual(f(10), "just now")
        self.assertEqual(f(45 * 60), "45 min")
        self.assertEqual(f(2 * 3600 + 5), "2 h")
        self.assertEqual(f(3 * 86400), "3 d")


class ContextNudge(Base):
    def setUp(self):
        super().setUp()
        self.config("[nudge]\ncontext_window = 300000\n")

    def test_sequence(self):
        seq = [100000, 170000, 185000, 200000, 275000, 280000, 100000, 190000]
        fired = [c for c in seq if self.post(c)]
        # 185k fires (low), 275k fires (high); 100k re-arms; 190k fires again
        self.assertEqual(fired, [185000, 275000, 190000])

    def test_line_text(self):
        out = self.post(270400)
        self.assertEqual(out["additionalContext"],
                         "Synapse: the context is about 270k tokens (window 300k, from your config). "
                         "A /synapse:checkpoint before the next stage or before stepping away keeps /clear free.")
        self.assertEqual(out["hookEventName"], "PostToolUse")

    def test_high_first_marks_low(self):
        self.assertTrue(self.post(280000))
        self.assertIsNone(self.post(190000))

    def test_cap_of_three(self):
        res = []
        for c in (200000, 100000) * 4:
            res.append(bool(self.post(c)))
        self.assertEqual(sum(res), 3)

    def test_failure_event(self):
        self.assertEqual(self.post(200000, event="PostToolUseFailure")["hookEventName"],
                         "PostToolUseFailure")

    def test_exempt_and_dispatch_tools_run(self):
        self.assertTrue(self.post(200000, tool="Agent"))
        self.assertTrue(self.post(280000, tool="Bash", tool_input={"command": "synapse x"}))

    def test_window_zero_silent(self):
        self.config("[nudge]\ncontext_window = 0\n")
        self.assertIsNone(self.post(290000))

    def test_custom_window(self):
        self.config("[nudge]\ncontext_window = 100000\n")
        self.assertIn("about 70k", self.post(70000)["additionalContext"])

    def test_agent_id_silent(self):
        self.assertIsNone(self.post(290000, agent_id="a1"))

    def test_corrupt_state_starts_fresh(self):
        (self.home / "state").mkdir()
        (self.home / "state" / "context-s1.json").write_text("{nope")
        self.assertTrue(self.post(200000))

    def test_combined_with_dispatch(self):
        self.config("[nudge]\ncalls = 1\ncontext_window = 300000\n[gate]\nmin_context = 0.9\n")
        out = self.post(200000)
        lines = out["additionalContext"].split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("hands-on calls", lines[0])
        self.assertIn("context is about 200k", lines[1])

    def test_parallel_hooks_fire_once(self):
        write(self.tr, [usage_entry(200000)])
        stdin = {"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Read",
                 "transcript_path": str(self.tr)}
        for trial in range(3):
            self.setUp()
            write(self.tr, [usage_entry(200000)])
            with ThreadPoolExecutor(8) as ex:
                outs = list(ex.map(lambda _: run(stdin, self.home).stdout, range(8)))
            self.assertEqual(sum(1 for o in outs if o.strip()), 1, outs)

    def test_compaction_boundary_is_stale(self):
        boundary = json.dumps({"type": "system", "subtype": "compact_boundary",
                               "compactMetadata": {"preTokens": 400105, "postTokens": 20000}})
        summary = json.dumps({"type": "user", "isCompactSummary": True, "message": "s"})
        write(self.tr, [usage_entry(400000, ago_s=7200), boundary, summary])
        self.assertIsNone(continuation.last_usage(str(self.tr)))
        self.assertIsNone(self.send({"session_id": "s1", "hook_event_name": "PostToolUse",
                                     "tool_name": "Bash", "transcript_path": str(self.tr)}))
        self.assertIsNone(self.send({"session_id": "s1", "hook_event_name": "UserPromptSubmit",
                                     "transcript_path": str(self.tr)}))
        # an assistant entry after the boundary counts again
        write(self.tr, [usage_entry(400000, ago_s=7200), boundary, summary, usage_entry(250000)])
        self.assertEqual(continuation.last_usage(str(self.tr))["context"], 250000)

    def test_dispatch_alone_unchanged(self):
        self.config("[nudge]\ncalls = 1\n")
        out = self.post(1000)
        self.assertNotIn("\n", out["additionalContext"])


class ResumeTime(Base):
    def setUp(self):
        super().setUp()
        self.config("[nudge]\ncontext_window = 300000\n")

    def prompt(self, ctx, ago_s, ttl="1h", **kw):
        write(self.tr, [usage_entry(ctx, ago_s=ago_s, ttl=ttl)])
        return self.send({"session_id": "s1", "hook_event_name": "UserPromptSubmit",
                          "prompt": "hi", "transcript_path": str(self.tr), **kw})

    def test_fires_after_ttl(self):
        out = self.prompt(300000, 2 * 3600 + 60)
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertEqual(out["additionalContext"],
                         "Synapse: idle 2 h since the last request, so the prompt cache has expired "
                         "and this request rewrites about 300k tokens. A /synapse:checkpoint before "
                         "stepping away keeps /clear free.")

    def test_silent_inside_ttl(self):
        self.assertIsNone(self.prompt(300000, 1800))

    def test_five_minute_ttl(self):
        self.assertIn("idle 10 min", self.prompt(300000, 600, ttl="5m")["additionalContext"])
        self.assertIsNone(self.prompt(300000, 600, ttl="1h"))

    def test_unknown_ttl_is_one_hour(self):
        self.assertIsNone(self.prompt(300000, 1800, ttl=None))
        self.assertTrue(self.prompt(300000, 4000, ttl=None))

    def test_small_context_silent(self):
        self.assertIsNone(self.prompt(100000, 7200))

    def test_window_zero_silent(self):
        self.config("[nudge]\ncontext_window = 0\n")
        self.assertIsNone(self.prompt(300000, 7200))

    def test_still_resets_dispatch_count(self):
        st = self.home / "state"
        st.mkdir()
        (st / "nudge-s1.count").write_bytes(b"...")
        self.prompt(1000, 0)
        self.assertFalse((st / "nudge-s1.count").exists())


def boundary(pre, trigger="auto"):
    return json.dumps({"type": "system", "subtype": "compact_boundary",
                       "compactMetadata": {"trigger": trigger, "preTokens": pre, "postTokens": 20000}})


def model_entry(ctx, model):
    return usage_entry(ctx, message={"model": model, "usage": json.loads(usage_entry(ctx))["message"]["usage"]})


class Derived(Base):
    """The window when [nudge] context_window is unset."""

    def post(self, lines, sid="s1", **extra):
        write(self.tr, lines)
        return self.send({"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                          "tool_input": {}, "transcript_path": str(self.tr), **extra})

    def text(self, out):
        return out["additionalContext"] if out else None

    def test_explicit_wins_over_boundary_and_model(self):
        self.config("[nudge]\ncontext_window = 100000\n")
        out = self.post([boundary(400000), model_entry(70000, "claude-opus-5-5")])
        self.assertIn("about 70k tokens (window 100k, from your config)", self.text(out))

    def test_explicit_zero_off(self):
        self.config("[nudge]\ncontext_window = 0\n")
        self.assertIsNone(self.post([boundary(100000), model_entry(200000, "claude-sonnet-5-5")]))

    def state(self, sid="s1"):
        f = self.home / "state" / f"context-{sid}.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def test_auto_boundary_lowers_model_window(self):
        # sonnet-4-5 is 150k; an auto-compaction at 120k lowers it
        out = self.post([boundary(120000), model_entry(75000, "claude-sonnet-4-5")])
        self.assertIn("about 75k tokens (window 120k, from an earlier auto-compaction)", self.text(out))

    def test_boundary_never_raises_window(self):
        out = self.post([boundary(968000), model_entry(100000, "claude-sonnet-4-5")])
        self.assertIn("(window 150k, from the model)", self.text(out))
        out = self.post([boundary(195000), model_entry(100000, "claude-sonnet-4-5")], sid="s2")
        self.assertIn("(window 150k, from the model)", self.text(out))

    def test_smallest_of_boundaries_kept(self):
        self.post([boundary(190000), model_entry(10000, "claude-opus-5-5")])
        self.assertEqual(self.state()["observed"], 190000)
        self.post([boundary(170000), model_entry(10000, "claude-opus-5-5")])
        self.assertEqual(self.state()["observed"], 170000)
        self.post([boundary(210000), model_entry(10000, "claude-opus-5-5")])
        self.assertEqual(self.state()["observed"], 170000)
        out = self.post([model_entry(160000, "claude-opus-5-5")])
        self.assertIn("window 170k, from an earlier auto-compaction", self.text(out))

    def test_model_switch_down_uses_smaller(self):
        self.post([boundary(190000), model_entry(10000, "claude-opus-5-5")])
        out = self.post([model_entry(120000, "claude-sonnet-4-5")])  # persisted 190k > 150k: model wins
        self.assertIn("(window 150k, from the model)", self.text(out))

    def test_manual_boundary_ignored(self):
        out = self.post([boundary(75000, "manual"), model_entry(140000, "claude-sonnet-4-5")])
        self.assertIn("window 150k, from the model", self.text(out))
        self.assertNotIn("observed", self.state())

    def test_observed_persists_after_boundary_scrolls_out(self):
        self.post([boundary(120000), model_entry(10000, "claude-opus-5-5")])
        self.assertEqual(self.state()["observed"], 120000)
        out = self.post([model_entry(80000, "claude-opus-5-5")])
        self.assertIn("window 120k, from an earlier auto-compaction", self.text(out))

    def test_state_keeps_epoch_and_observed(self):
        self.post([boundary(200000), model_entry(125000, "claude-sonnet-4-5")])
        self.post([model_entry(50000, "claude-sonnet-4-5")])  # drop re-arms: epoch bumps
        state = self.state()
        self.assertEqual((state["epoch"], state["observed"]), (1, 200000))

    def test_observed_written_only_when_it_changes(self):
        self.post([boundary(120000), model_entry(10000, "claude-opus-5-5")])
        f = self.home / "state" / "context-s1.json"
        before = f.stat().st_mtime_ns
        self.post([boundary(130000), model_entry(10000, "claude-opus-5-5")])
        self.assertEqual(f.stat().st_mtime_ns, before)

    def test_state_write_failure_is_survivable(self):
        import paths
        from unittest import mock
        os.environ["SYNAPSE_HOME"] = str(self.home)
        try:
            u = {"model": "claude-opus-5-5"}
            with mock.patch.object(continuation.os, "replace", side_effect=PermissionError):
                w = continuation.window_for(paths, "s1", u, 120000)
            self.assertEqual(w, (120000, "from an earlier auto-compaction"))
            self.assertEqual(list((self.home / "state").glob("*.tmp")), [])
            with mock.patch.object(continuation, "window_for", side_effect=RuntimeError):
                write(self.tr, [usage_entry(300000, ago_s=7200)])
                self.assertEqual(continuation.resume_time_line(
                    paths, {"transcript_path": str(self.tr)}, "s1"), "")
        finally:
            os.environ.pop("SYNAPSE_HOME", None)

    def test_model_rule(self):
        big = ("claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5", "claude-haiku-5-5",
               "claude-opus-4-7", "claude-opus-4.7", "claude-opus-4-8", "claude-opus-5-5[1m]",
               "claude-sonnet-4-5[1m]", "Claude-OPUS-5-5", "haiku", "opus", "sonnet", "fable", "")
        small = ("claude-opus-4-6", "claude-opus-4-1", "claude-sonnet-4-5-20250929", "claude-sonnet-4-20250514",
                 "claude-haiku-4-5", "claude-opus-4.6", "claude-3-5-sonnet-20241022", "claude-3-opus-20240229",
                 "gpt-4o", "gateway-model-v2", "<synthetic>")
        for model, window, ctx in [(m, "300k", 190000) for m in big] + [(m, "150k", 100000) for m in small]:
            with self.subTest(model=model):
                self.setUp()
                out = self.post([model_entry(ctx, model)])
                self.assertIn(f"(window {window}, from the model)", self.text(out))

    def test_model_rule_marks(self):
        self.assertIsNone(self.post([model_entry(80000, "claude-haiku-4-5")]))   # below 90k
        self.assertTrue(self.post([model_entry(90000, "claude-haiku-4-5")], sid="s2"))
        self.assertIsNone(self.post([model_entry(150000, "claude-opus-5-5")], sid="s3"))  # below 180k

    def test_missing_model_is_big_window(self):
        self.assertIn("window 300k, from the model", self.text(self.post([usage_entry(190000)])))

    def test_resume_time_uses_derived_window(self):
        req = {"session_id": "s1", "hook_event_name": "UserPromptSubmit", "transcript_path": str(self.tr)}
        write(self.tr, [boundary(200000), usage_entry(130000, ago_s=7200)])
        self.assertIn("rewrites about 130k tokens", self.send(req)["additionalContext"])
        write(self.tr, [boundary(200000), usage_entry(110000, ago_s=7200)])
        self.assertIsNone(self.send(dict(req, session_id="s2")))
        write(self.tr, [usage_entry(100000, ago_s=7200)])  # no model: 300k window, 100k is below 60%
        self.assertIsNone(self.send(dict(req, session_id="s3")))


class ResumePointer(Base):
    def setUp(self):
        super().setUp()
        self.proj = self.dir / "proj"
        self.cur = self.proj / ".claude-work" / "current"
        self.cur.mkdir(parents=True)
        (self.proj / ".git").mkdir()
        self.ex = self.cur / "EXECUTION.md"

    def start(self, source="compact"):
        out = self.send({"session_id": "s1", "hook_event_name": "SessionStart",
                         "source": source, "cwd": str(self.proj)})
        return out["additionalContext"] if out else None

    def stamp(self, ago_min):
        t = datetime.now().astimezone() - timedelta(minutes=ago_min)
        return t.strftime("%Y-%m-%d %H:%M %z"), t.strftime("%Y-%m-%d %H:%M")

    def test_with_stamp_and_notes(self):
        s, shown = self.stamp(12)
        s = s[:-2] + ":" + s[-2:]
        self.ex.write_text(f"# E\n## Resume\nCheckpoint written: {s}\nmore\n## Other\n")
        (self.cur / "NOTES.md").write_text("n")
        text = self.start()
        self.assertEqual(text,
            f"Synapse: work in progress is recorded in .claude-work/current/EXECUTION.md under "
            f"## Resume (checkpoint written {shown}, 12 min ago). If this conversation continues "
            f"that work, read it before acting; NOTES.md beside it holds the checkpoint's facts "
            f"and decisions.")
        self.assertLess(len(text), 400)
        self.assertEqual(self.start("clear"), text)

    def test_stamp_outside_section_ignored(self):
        s, _ = self.stamp(5)
        self.ex.write_text(f"## Resume\nnothing\n## Other\nCheckpoint written: {s}\n")
        self.assertIn("file modified", self.start())

    def test_mtime_fallback_no_notes(self):
        self.ex.write_text("## resume\nbody\n")
        old = datetime.now().timestamp() - 3 * 3600
        os.utime(self.ex, (old, old))
        text = self.start()
        self.assertIn("(file modified ", text)
        self.assertIn(", 3 h ago)", text)
        self.assertNotIn("NOTES.md", text)

    def test_no_section_no_file_other_sources(self):
        self.assertIsNone(self.start())
        self.ex.write_text("# E\n### Resume later\n")
        self.assertIsNone(self.start())
        self.ex.write_text("## Resume\nx\n")
        for src in ("startup", "resume", "fork", None):
            self.assertIsNone(self.start(src))

    def test_path_relative_to_project_root_from_subfolder(self):
        self.ex.write_text("## Resume\nx\n")
        sub = self.proj / "src" / "deep"
        sub.mkdir(parents=True)
        out = self.send({"session_id": "s1", "hook_event_name": "SessionStart",
                         "source": "clear", "cwd": str(sub)})
        self.assertIn("recorded in .claude-work/current/EXECUTION.md under", out["additionalContext"])

    def test_still_prunes(self):
        st = self.home / "state"
        st.mkdir()
        old = st / "context-other.json"
        old.write_text("{}")
        t = datetime.now().timestamp() - 8 * 24 * 3600
        os.utime(old, (t, t))
        fresh = st / "context-fresh.json"
        fresh.write_text("{}")
        mark = st / "context-s1.low.0"
        mark.write_text("")
        os.utime(mark, (t, t))
        own = st / "context-s1.json"
        own.write_text("{}")
        os.utime(own, (t, t))
        self.start("startup")
        self.assertFalse(old.exists())
        self.assertTrue(own.exists() and mark.exists() and fresh.exists())


class NeverBlock(Base):
    def test_bad_inputs(self):
        for stdin in (b"{not json", b"", b"[]"):
            r = run(stdin, self.home)
            self.assertEqual((r.returncode, r.stdout), (0, b""))
        for tp in (None, 7, str(self.dir), str(self.dir / "nope")):
            self.assertIsNone(self.send({"session_id": "s1", "hook_event_name": "PostToolUse",
                                         "tool_name": "Bash", "transcript_path": tp}))
            self.assertIsNone(self.send({"session_id": "s1", "hook_event_name": "UserPromptSubmit",
                                         "transcript_path": tp}))

    def test_bad_config(self):
        write(self.tr, [usage_entry(290000)])
        self.config('[nudge]\ncontext_window = "x"\n')
        r = run({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash",
                 "transcript_path": str(self.tr)}, self.home)
        self.assertEqual((r.returncode, r.stdout), (0, b""))


if __name__ == "__main__":
    unittest.main()
