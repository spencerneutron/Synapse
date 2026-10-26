"""Schema v2, hybrid recall, supersession, and the v1 -> v2 upgrade.

Needs sqlite-vec (CI installs it) and an sqlite3 that can load extensions;
skips otherwise. A deterministic bag-of-words embedder stands in for Ollama.
"""

import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import helpers  # noqa: F401  (isolated SYNAPSE_HOME)
import extract
import paths
import recall

try:
    import sqlite_vec
    _probe = sqlite3.connect(":memory:")
    _probe.enable_load_extension(True)
    _probe.load_extension(sqlite_vec.loadable_path())
    VEC = True
except Exception:  # missing package, or an sqlite3 without extension loading
    VEC = False


def fake_embed(text: str, input_type: str = "document") -> list[float]:
    """Each word lights a few dimensions, so texts sharing words are near."""
    v = [0.0] * extract.EMBEDDING_DIM
    for w in re.findall(r"\w+", text.lower()):
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        for i in range(3):
            v[(h >> (i * 10)) % extract.EMBEDDING_DIM] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@unittest.skipUnless(VEC, "sqlite-vec with extension loading not available")
class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["SYNAPSE_HOME"] = str(self.tmp / "home")
        self._saved = (extract.embed_text, extract.embed_batch, recall.embed_text)
        extract.embed_text = recall.embed_text = fake_embed
        extract.embed_batch = lambda texts: [fake_embed(t) for t in texts]
        self.r = paths.resolve(cwd=self.tmp)
        self.db = self.r.db
        self.conn = extract.db_connect(self.db)
        extract.db_init(self.conn, self.db)
        self.add("archive/App/PLAN_1.md", "archive", "App", "QuickAddTracker frames stay out of view bodies")
        self.add("archive/App/PLAN_1.md", "archive", "App", "scroll performance tuning for the work view", idx=1)
        self.add("vault/Decisions/Use A.md", "decision", "veilmx", "forward ops mail raw to the operator")
        self.add("vault/Decisions/Use B.md", "decision", "VeilMX", "wrap ops mail in signed first-party messages")
        self.add("vault/Patterns/Mail.md", "pattern", "VeilMX", "mail signing pattern for ops messages")

    def tearDown(self):
        self.conn.close()
        extract.embed_text, extract.embed_batch, recall.embed_text = self._saved

    def add(self, path, kind, project, text, idx=0):
        chunk = extract.Chunk(text=text, source_path=path, source_type=kind,
                              session_id=None, project=project, chunk_index=idx, metadata={})
        extract.store_chunks(self.conn, [chunk])

    def search(self, q, **kw):
        return recall.search(self.conn, q, kw.pop("top_k", 5), **kw)

    def test_schema_is_current_and_indexes_agree(self):
        self.assertEqual(extract.schema_version(self.conn), 2)
        counts = [self.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("chunks", "chunks_vec", "chunks_fts")]
        self.assertEqual(counts, [5, 5, 5])

    def test_fts_query_quotes_every_word(self):
        self.assertEqual(recall.fts_query('a "b" OR c*'), '"a" OR "b" OR "OR" OR "c"')
        self.assertIsNone(recall.fts_query("!!!"))

    def test_fusion_rewards_agreement_and_keeps_vector_order_on_ties(self):
        self.assertEqual(recall.fuse([1, 2], [2, 3]), [(2, "both"), (1, "vector"), (3, "keyword")])
        self.assertEqual(recall.fuse([7], [8]), [(7, "vector"), (8, "keyword")])

    def test_filters_are_exact_and_project_ignores_case(self):
        hits = self.search("ops mail", project="VeilMX", source_type="decision")
        self.assertEqual({h["stored_path"] for h in hits}, {"vault/Decisions/Use A.md", "vault/Decisions/Use B.md"})
        self.assertTrue(all(h["source_type"] == "decision" for h in hits))

    def test_keyword_mode_finds_identifiers(self):
        hits = self.search("QuickAddTracker", mode="keyword")
        self.assertEqual(hits[0]["stored_path"], "archive/App/PLAN_1.md")
        self.assertEqual(hits[0]["match"], "keyword")

    def test_supersede_hides_old_decision_and_updates_note(self):
        note = self.tmp / "vault" / "Decisions" / "Use A.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\ntype: decision\nstatus: active\n---\n# Use A\n")
        self.r.vault_path = self.tmp / "vault"
        os.environ["SYNAPSE_HOME"] = str(self.tmp / "home")
        cfg = self.tmp / "home" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(f'[stores.main]\nvault_path = "{(self.tmp / "vault").as_posix()}"\n')
        out = StringIO()
        with redirect_stdout(out):
            extract.cmd_supersede(Namespace(old="[[Use A]]", by="[[Use B]]", folder="Decisions", db=self.db))
        report = json.loads(out.getvalue())
        self.assertEqual(report["chunks_marked"], 1)
        self.assertIn("status: superseded", note.read_text())
        self.assertIn('superseded_by: "[[Use B]]"', note.read_text())
        self.assertNotIn("vault/Decisions/Use A.md", {h["stored_path"] for h in self.search("ops mail")})
        shown = {h["stored_path"]: h for h in self.search("ops mail", include_superseded=True)}
        self.assertEqual(shown["vault/Decisions/Use A.md"]["status"], "superseded")
        self.assertEqual(shown["vault/Decisions/Use A.md"]["superseded_by"], "vault/Decisions/Use B.md")


    def test_project_filter_folds_non_ascii_case_in_both_searches(self):
        self.add("archive/Ü/PLAN_9.md", "archive", "Übersicht", "QuickAddTracker in the overview app", idx=9)
        for mode in ("keyword", "vector"):
            hits = self.search("QuickAddTracker", project="ÜBERSICHT", mode=mode)
            self.assertEqual([h["stored_path"] for h in hits], ["archive/Ü/PLAN_9.md"], mode)

    def test_supersede_without_vault_path_never_calls_obsidian(self):
        import vault_write
        saved = vault_write.vault_path
        vault_write.vault_path = lambda: self.fail("must not call the Obsidian CLI")
        try:
            with redirect_stdout(StringIO()) as out:
                extract.cmd_supersede(Namespace(old="[[Use A|old]]", by="[[Use B#Decision]]",
                                                folder="Decisions", db=self.db))
        finally:
            vault_write.vault_path = saved
        report = json.loads(out.getvalue())
        self.assertEqual((report["chunks_marked"], report["note_updated"]), (1, None))
        self.assertEqual(report["by"], "vault/Decisions/Use B.md")

    def test_supersession_survives_a_reembed_of_an_unchanged_note(self):
        with redirect_stdout(StringIO()):
            extract.cmd_supersede(Namespace(old="Use A.md", by="[[Use B]]", folder="Decisions", db=self.db))
        note = self.tmp / "Decisions" / "Use A.md"
        note.parent.mkdir(parents=True)
        note.write_text("---\ntype: decision\nproject: veilmx\nstatus: active\n---\nforward ops mail raw\n")
        with redirect_stdout(StringIO()):
            extract.cmd_embed_note(Namespace(path=str(note), project=None, db=self.db))
        statuses = {r[0] for r in self.conn.execute(
            "SELECT status FROM chunks WHERE source_path = 'vault/Decisions/Use A.md'")}
        self.assertEqual(statuses, {"superseded"})


class FrontMatterTests(unittest.TestCase):
    def write(self, text):
        p = Path(tempfile.mkdtemp()) / "n.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_replaces_keys_and_keeps_other_lines(self):
        import vault_write
        p = self.write("---\ntype: decision\n\nstatus: active\nstatus_note: x\n---\n# T\n\n---\nbody\n")
        vault_write.set_frontmatter(p, {"status": "superseded"})
        self.assertEqual(p.read_text(), "---\ntype: decision\n\nstatus: superseded\nstatus_note: x\n---\n# T\n\n---\nbody\n")

    def test_empty_block_and_bom(self):
        import vault_write
        p = self.write("---\n---\n# T\n\n---\nbody\n")
        vault_write.set_frontmatter(p, {"status": "superseded"})
        self.assertEqual(p.read_text(), "---\nstatus: superseded\n---\n# T\n\n---\nbody\n")
        q = self.write("\ufeff---\nstatus: active\n---\nx\n")
        vault_write.set_frontmatter(q, {"status": "superseded"})
        self.assertEqual(q.read_text(), "---\nstatus: superseded\n---\nx\n")


@unittest.skipUnless(VEC, "sqlite-vec with extension loading not available")
class UpgradeTests(unittest.TestCase):
    def test_v1_store_upgrades_in_place_without_changing_vectors(self):
        tmp = Path(tempfile.mkdtemp())
        db = tmp / "vectors.db"
        conn = extract.db_connect(db)
        conn.executescript(f"""
            CREATE TABLE chunks (id INTEGER PRIMARY KEY, chunk_hash TEXT UNIQUE NOT NULL,
                source_path TEXT NOT NULL, source_type TEXT NOT NULL, session_id TEXT, project TEXT,
                chunk_index INTEGER NOT NULL, text TEXT NOT NULL, metadata JSON,
                embedding_model TEXT NOT NULL, embedding_dim INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding FLOAT[{extract.EMBEDDING_DIM}] distance_metric=cosine);
        """)
        for i, (text, project) in enumerate([("alpha notes", "App"), ("beta notes", None)], 1):
            conn.execute("INSERT INTO chunks VALUES (?, ?, ?, 'archive', NULL, ?, 0, ?, '{}', ?, ?, '2026-01-01')",
                         (i, f"h{i}", f"archive/App/PLAN_{i}.md", project, text,
                          extract.EMBEDDING_MODEL, extract.EMBEDDING_DIM))
            conn.execute("INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)", (i, json.dumps(fake_embed(text))))
        conn.commit()
        before = {r[0]: bytes(r[1]) for r in conn.execute("SELECT rowid, embedding FROM chunks_vec")}
        conn.close()
        probe = extract.db_connect(db)
        self.assertEqual(extract.schema_version(probe), 1)
        probe.close()

        with redirect_stdout(StringIO()):
            self.assertEqual(extract.cmd_upgrade(Namespace(db=db)), 0)
        conn = extract.db_connect(db)
        self.assertEqual(extract.schema_version(conn), 2)
        after = {r[0]: bytes(r[1]) for r in conn.execute("SELECT rowid, embedding FROM chunks_vec")}
        self.assertEqual(after, before)
        self.assertEqual(conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0], 2)
        self.assertEqual({r[0] for r in conn.execute("SELECT status FROM chunks")}, {"active"})
        self.assertEqual(len(list(tmp.glob("vectors.db.bak-*"))), 1)
        conn.close()

        out = StringIO()
        with redirect_stdout(out):
            extract.cmd_upgrade(Namespace(db=db))
        self.assertIn("already schema v2", out.getvalue())

    def test_upgrade_refuses_a_newer_schema(self):
        db = Path(tempfile.mkdtemp()) / "vectors.db"
        conn = extract.db_connect(db)
        extract.db_init(conn, db)
        conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
        conn.commit()
        with self.assertRaises(SystemExit) as cm:
            extract.cmd_upgrade(Namespace(db=db))
        conn.close()
        self.assertIn("newer", str(cm.exception))
        self.assertEqual(list(db.parent.glob("vectors.db.bak-*")), [])

    def test_commands_refuse_an_old_schema(self):
        tmp = Path(tempfile.mkdtemp())
        db = tmp / "vectors.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY)")
        conn.commit()
        with self.assertRaises(SystemExit):
            extract.require_current(conn, db)
        conn.close()


if __name__ == "__main__":
    unittest.main()
