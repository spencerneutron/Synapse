"""`synapse extract check-candidates`: prior-note lookup for extraction candidates.

Needs sqlite-vec (CI installs it); skips otherwise. The bag-of-words embedder
from test_retrieval stands in for Ollama.
"""

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import helpers  # noqa: F401  (isolated SYNAPSE_HOME)
import extract
import paths
import recall
from test_retrieval import VEC, fake_embed


def run_cmd(*argv):
    """(exit code, stdout) of `synapse extract <argv>`."""
    out = StringIO()
    with redirect_stdout(out):
        code = extract.main(list(argv))
    return code, out.getvalue()


@unittest.skipUnless(VEC, "sqlite-vec with extension loading not available")
class CheckCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["SYNAPSE_HOME"] = str(self.tmp / "home")
        self._saved = (extract.embed_text, recall.embed_text)
        extract.embed_text = recall.embed_text = fake_embed
        self.r = paths.resolve(cwd=self.tmp)
        self.conn = extract.db_connect(self.r.db)
        extract.db_init(self.conn, self.r.db)

    def tearDown(self):
        self.conn.close()
        extract.embed_text, recall.embed_text = self._saved

    def add(self, title, kind, text, session="old-session", status="active"):
        folder = {"decision": "Decisions", "fact": "Facts", "pattern": "Patterns"}[kind]
        chunk = extract.Chunk(text=text, source_path=f"vault/{folder}/{title}.md", source_type=kind,
                              session_id=session, project="App", chunk_index=0, metadata={})
        extract.store_chunks(self.conn, [chunk], status=status)

    def cands(self, *items):
        f = self.tmp / "cands.json"
        f.write_text(json.dumps(list(items)))
        return f

    def check(self, *items, session="new-session", extra=()):
        code, out = run_cmd("check-candidates", str(self.cands(*items)), "--session", session, *extra)
        self.assertEqual(code, 0)
        return json.loads(out)["candidates"]

    def cand(self, concept="e2e workflow trigger schedule", type="decision"):
        return {"type": type, "title": "Keep the e2e workflow scheduled", "concept": concept}

    def test_threshold_boundary(self):
        self.add("Nightly e2e", "decision", "e2e workflow trigger schedule nightly")
        score = recall.search(self.conn, "e2e workflow trigger schedule", 1)[0]["score"]
        self.assertGreater(score, 0.3)
        at = self.check(self.cand(), extra=("--threshold", str(score)))[0]["hits"]
        self.assertEqual([h["title"] for h in at], ["Nightly e2e"])
        above = self.check(self.cand(), extra=("--threshold", str(score + 0.01)))[0]["hits"]
        self.assertEqual(above, [])

    def test_default_threshold_is_070(self):
        self.assertEqual(recall.CANDIDATE_MIN_SCORE, 0.70)
        self.add("Weak", "decision", "e2e plus many other unrelated words here today again more")
        self.add("Strong", "decision", "e2e workflow trigger schedule")
        hits = self.check(self.cand())[0]["hits"]
        self.assertEqual([h["title"] for h in hits], ["Strong"])
        self.assertTrue(all(h["score"] >= 0.70 for h in hits))

    def test_hit_fields_and_type_filter(self):
        self.add("A decision", "decision", "e2e workflow trigger schedule")
        self.add("A fact", "fact", "e2e workflow trigger schedule")
        (res,) = self.check(self.cand(type="fact"))
        self.assertEqual((res["type"], res["concept"]), ("fact", "e2e workflow trigger schedule"))
        (hit,) = res["hits"]
        self.assertEqual(hit["title"], "A fact")
        self.assertEqual(hit["session_id"], "old-session")
        self.assertEqual(hit["path"], "vault/Facts/A fact.md")
        self.assertIn("e2e workflow", hit["snippet"])
        self.assertIn("score", hit)

    def test_searches_local_scope_only(self):
        self.add("Mine", "decision", "e2e workflow trigger schedule")
        calls = []
        real = recall.search_all

        def spy(*a, **kw):
            calls.append(kw.get("scope"))
            return real(*a, **kw)

        recall.search_all = spy
        try:
            self.check(self.cand())
        finally:
            recall.search_all = real
        self.assertEqual(calls, ["local"])

    def test_top_three_cap(self):
        for i in range(5):
            self.add(f"Note {i}", "decision", f"e2e workflow trigger schedule variant{i}")
        hits = self.check(self.cand(), extra=("--threshold", "0.1"))[0]["hits"]
        self.assertEqual(len(hits), 3)

    def test_own_session_hits_are_dropped_before_the_cap(self):
        for i in range(3):
            self.add(f"Own {i}", "decision", "e2e workflow trigger schedule", session="new-session")
        self.add("Prior", "decision", "e2e workflow trigger schedule nightly")
        hits = self.check(self.cand())[0]["hits"]
        self.assertEqual([h["title"] for h in hits], ["Prior"])

    def test_superseded_notes_stay_hidden(self):
        self.add("Old", "decision", "e2e workflow trigger schedule", status="superseded")
        self.assertEqual(self.check(self.cand())[0]["hits"], [])

    def test_no_match_is_exit_zero_with_empty_hits(self):
        self.add("Unrelated", "decision", "paint the shed green")
        code, out = run_cmd("check-candidates", str(self.cands(self.cand())), "--session", "s")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["candidates"][0]["hits"], [])

    def test_zero_candidates(self):
        for body in ([], {"candidates": []}):
            f = self.tmp / "none.json"
            f.write_text(json.dumps(body))
            code, out = run_cmd("check-candidates", str(f), "--session", "s")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["candidates"], [])

    def test_wrapped_candidates_object_is_accepted(self):
        self.add("Prior", "decision", "e2e workflow trigger schedule")
        f = self.tmp / "wrapped.json"
        f.write_text(json.dumps({"candidates": [self.cand()]}))
        code, out = run_cmd("check-candidates", str(f), "--session", "s")
        self.assertEqual(len(json.loads(out)["candidates"][0]["hits"]), 1)

    def test_bad_input_exits_nonzero_with_a_clear_error(self):
        bad = [
            [{"type": "session", "title": "t", "concept": "c"}],
            [{"type": "fact", "title": "t"}],
            [{"type": "fact", "title": "t", "concept": "  "}],
            ["not an object"],
        ]
        for items in bad:
            with self.subTest(items=items), self.assertRaises(SystemExit) as cm:
                run_cmd("check-candidates", str(self.cands(*items)), "--session", "s")
            self.assertIn("error:", str(cm.exception.code))
        notjson = self.tmp / "x.json"
        notjson.write_text("{nope")
        with self.assertRaises(SystemExit):
            run_cmd("check-candidates", str(notjson), "--session", "s")


if __name__ == "__main__":
    unittest.main()
