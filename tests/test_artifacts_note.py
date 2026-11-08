import sqlite3
import tempfile
import unittest
from pathlib import Path

from helpers import LIB  # noqa: F401  (sets up the isolated home and sys.path)

import archive
import extract
import vault_write

L1 = ("First", "https://claude.ai/artifact/abc")
L2 = ("Second", "https://claude.ai/code/artifact/d-e_f")
NOTE = '---\ntype: session\ndate: 2026-01-01\nproject: p\ntags:\n  - session\n---\n\n# Session\n\n## Outcome\n\nDone.\n'


class FrontmatterParserTests(unittest.TestCase):
    def fm(self, text):
        return extract.parse_frontmatter(f"---\n{text}\n---\nbody")[0]

    def test_flat_unchanged(self):
        self.assertEqual(self.fm('a: "x y"\nb: \'z\'\nc: 3\nd: []'),
                         {"a": "x y", "b": "z", "c": "3", "d": "[]"})

    def test_block_list(self):
        fm = self.fm('k: v\nartifacts:\n  - "https://x/1"\n  - \'two\'\n  - three\nafter: 1')
        self.assertEqual(fm["artifacts"], ["https://x/1", "two", "three"])
        self.assertEqual((fm["k"], fm["after"]), ("v", "1"))

    def test_unindented_dash_and_escapes(self):
        fm = self.fm('l:\n- "a \\"q\\" \\\\ b"')
        self.assertEqual(fm["l"], ['a "q" \\ b'])

    def test_nested_map_ignored(self):
        fm = self.fm("m:\n  inner: 1\n  other: 2\nz: 9")
        self.assertEqual(fm, {"m": "", "z": "9"})

    def test_empty_key_without_items_is_string(self):
        self.assertEqual(self.fm("a:\nb: 1")["a"], "")


class PureWriterTests(unittest.TestCase):
    def test_new_note(self):
        out = extract.apply_artifacts(NOTE, [L1, L2])
        self.assertIn('artifacts:\n  - "https://claude.ai/artifact/abc"\n'
                      '  - "https://claude.ai/code/artifact/d-e_f"\n---\n', out)
        self.assertTrue(out.endswith("## Artifacts\n\n- [First](https://claude.ai/artifact/abc)\n"
                                     "- [Second](https://claude.ai/code/artifact/d-e_f)\n"))
        fm = extract.parse_frontmatter(out)[0]
        self.assertEqual(fm["artifacts"], [L1[1], L2[1]])
        self.assertIn("tags:\n  - session\n", out)

    def test_existing_section_in_middle_stays_in_place(self):
        note = NOTE + "\n## Artifacts\n\n- [old](https://claude.ai/artifact/old1)\n\n## Open\n\nQ?\n"
        out = extract.apply_artifacts(note, [L1])
        self.assertEqual(out.count("## Artifacts"), 1)
        self.assertNotIn("old1", out.split("---", 2)[2])
        self.assertIn("## Artifacts\n\n- [First](https://claude.ai/artifact/abc)\n\n## Open\n\nQ?\n", out)
        self.assertEqual(extract.apply_artifacts(out, [L1]), out)

    def test_subsection_under_artifacts_kept(self):
        note = (NOTE + "\n## Artifacts\n\n- [old](https://claude.ai/artifact/old1)\n\n"
                "### Notes\n\nKeep me.\n\n## Open\n\nQ?\n")
        out = extract.apply_artifacts(note, [L1, L2])
        self.assertIn("(https://claude.ai/code/artifact/d-e_f)\n\n### Notes\n\nKeep me.\n\n## Open\n\nQ?\n", out)
        self.assertNotIn("old1", out)
        self.assertEqual(extract.apply_artifacts(out, [L1, L2]), out)

    def test_later_h1_section_kept(self):
        note = NOTE + "\n## Artifacts\n\n- [old](https://claude.ai/artifact/old1)\n\n# Appendix\n\nStays.\n"
        out = extract.apply_artifacts(note, [L1])
        self.assertTrue(out.endswith("## Artifacts\n\n- [First](https://claude.ai/artifact/abc)\n\n# Appendix\n\nStays.\n"))
        self.assertEqual(extract.apply_artifacts(out, [L1]), out)

    def test_heading_inside_fence_ignored_and_fence_kept(self):
        note = NOTE + "\n```md\n## Artifacts\n\n- [x](https://claude.ai/artifact/fenced)\n```\n\nAfter.\n"
        out = extract.apply_artifacts(note, [L1])
        self.assertIn("```md\n## Artifacts\n\n- [x](https://claude.ai/artifact/fenced)\n```\n\nAfter.\n", out)
        self.assertTrue(out.endswith("\n\n## Artifacts\n\n- [First](https://claude.ai/artifact/abc)\n"))
        self.assertEqual(extract.apply_artifacts(out, [L1]), out)

    def test_odd_line_separators_untouched(self):
        note = NOTE + "\nA\x0cB\u2028C\n"
        out = extract.apply_artifacts(note, [L1])
        self.assertIn("A\x0cB\u2028C\n", out)
        self.assertEqual(extract.apply_artifacts(out, [L1]), out)

    def test_frontmatter_edge_cases_make_one_block(self):
        for text in ("\ufeff" + NOTE, "---\n---\n# T\n", "---\ntype: session\n---", "---\ntype: session\n---  \n# T\n"):
            out = extract.apply_artifacts(text, [L1])
            self.assertEqual(out.count("---\n"), 2, repr(out))
            self.assertTrue(out.startswith("---\n"), repr(out))
            self.assertEqual(extract.parse_frontmatter(out)[0]["artifacts"], [L1[1]])
            self.assertEqual(extract.apply_artifacts(out, [L1]), out)
        self.assertIn("type: session", extract.apply_artifacts("---\ntype: session\n---", [L1]))

    def test_existing_key_replaced(self):
        note = NOTE.replace("tags:", 'artifacts:\n  - "old"\n  - "older"\ntags:')
        out = extract.apply_artifacts(note, [L1])
        self.assertEqual(out.count("artifacts:"), 1)
        self.assertNotIn("old", out.split("# Session")[0])
        self.assertLess(out.index("artifacts:"), out.index("tags:"))
        self.assertIn("tags:\n  - session\n", out)

    def test_idempotent(self):
        once = extract.apply_artifacts(NOTE, [L1, L2])
        self.assertEqual(extract.apply_artifacts(once, [L1, L2]), once)
        bare = extract.apply_artifacts("# T\n\ntext\n", [L1])
        self.assertTrue(bare.startswith('---\nartifacts:\n  - "https://claude.ai/artifact/abc"\n---\n# T'))
        self.assertEqual(extract.apply_artifacts(bare, [L1]), bare)

    def test_parse_lines_validates(self):
        text = ("- [A](https://claude.ai/artifact/x1)\nnoise\n- [B](https://evil.example/artifact/x)\n"
                "- [C](https://claude.ai/code/artifact/y_2)\n")
        self.assertEqual(extract.parse_artifact_lines(text),
                         [("A", "https://claude.ai/artifact/x1"), ("C", "https://claude.ai/code/artifact/y_2")])

    def test_session_note_files(self):
        with tempfile.TemporaryDirectory() as t:
            for n in ("s1.md", "s1 v2.md", "s10.md", "s1 v2x.md", "other.md"):
                (Path(t) / n).write_text("x")
            self.assertEqual([f.name for f in extract.session_note_files(Path(t), "s1")],
                             ["s1 v2.md", "s1.md"])


class FrontmatterScalarTests(unittest.TestCase):
    def test_fm_str(self):
        self.assertEqual(extract.fm_str({"a": "x", "b": ["y"]}, "a"), "x")
        self.assertEqual(extract.fm_str({"b": ["y"]}, "b", "d"), "d")
        self.assertEqual(extract.fm_str({}, "c"), "")


try:
    import sqlite_vec
    _probe = sqlite3.connect(":memory:")
    _probe.enable_load_extension(True)
    _probe.load_extension(sqlite_vec.loadable_path())
    VEC = True
except Exception:  # missing package, or an sqlite3 without extension loading
    VEC = False


@unittest.skipUnless(VEC, "sqlite-vec with extension loading not available")
class EmbedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.vault, self.arch = t / "vault", t / "arch"
        (self.vault / "Sessions").mkdir(parents=True)
        self.arch.mkdir()
        self.note = self.vault / "Sessions" / "s1.md"
        self.note.write_text(NOTE, encoding="utf-8")
        (self.arch / "ARTIFACTS_s1.md").write_text(
            "- [Plan page](https://claude.ai/artifact/abc)\n", encoding="utf-8")
        self.saved = extract.embed_batch
        extract.embed_batch = lambda texts, input_type="document": [[0.0] * extract.EMBEDDING_DIM for _ in texts]
        self.addCleanup(lambda: setattr(extract, "embed_batch", self.saved))
        self.conn = extract.db_connect(t / "v.db")
        extract.db_init(self.conn, t / "v.db")
        self.r = extract.paths.resolve()
        self.r.vault_path = self.vault

    def run_step(self):
        return extract.add_session_artifacts(self.conn, self.r, self.arch, "s1", "p")

    def test_writes_and_embeds_idempotently(self):
        self.assertEqual(self.run_step(), 1)
        first = self.note.read_bytes()
        self.assertIn(b"## Artifacts", first)
        self.assertEqual(self.run_step(), 1)
        self.assertEqual(self.note.read_bytes(), first)
        rows = self.conn.execute("SELECT text, source_type, session_id FROM chunks").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("Plan page", rows[0]["text"])
        self.assertIn("https://claude.ai/artifact/abc", rows[0]["text"])
        self.assertEqual((rows[0]["source_type"], rows[0]["session_id"]), ("session", "s1"))

    def test_only_newest_version_written_and_embedded(self):
        old = self.vault / "Sessions" / "s1 v2.md"
        newer = self.vault / "Sessions" / "s1 v10.md"
        old.write_text(NOTE, encoding="utf-8")
        newer.write_text(NOTE, encoding="utf-8")
        stale = extract.Chunk(text="stale", source_path=extract.paths.to_stored_path(old, self.r),
                              source_type="session", session_id="s1", project="p", chunk_index=0, metadata={})
        extract.store_chunks(self.conn, [stale])
        self.assertEqual(self.run_step(), 1)
        self.assertNotIn(b"## Artifacts", old.read_bytes())
        self.assertNotIn(b"## Artifacts", self.note.read_bytes())
        self.assertIn(b"## Artifacts", newer.read_bytes())
        rows = self.conn.execute("SELECT source_path FROM chunks").fetchall()
        self.assertEqual([r["source_path"] for r in rows], [extract.paths.to_stored_path(newer, self.r)])

    def test_embed_note_with_list_type_does_not_break(self):
        n = self.vault / "Sessions" / "x.md"
        n.write_text("---\ntype:\n  - a\nproject:\n  - p\nsession_id:\n  - s\n---\n\n## H\n\nbody text\n",
                     encoding="utf-8")
        extract.embed_note(self.conn, n, "p")
        self.assertEqual(self.conn.execute("SELECT source_type FROM chunks").fetchone()[0], "note")

    def test_no_session_note_warns(self):
        self.note.unlink()
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.run_step(), 0)
        self.assertIn("no Session note", err.getvalue())

    def test_no_valid_lines_does_nothing(self):
        (self.arch / "ARTIFACTS_s1.md").write_text("junk\n")
        self.assertEqual(self.run_step(), 0)
        self.assertEqual(self.note.read_text(encoding="utf-8"), NOTE)


class BaseTests(unittest.TestCase):
    def test_created_once_never_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertTrue(vault_write.ensure_artifacts_base(Path(t)))
            f = Path(t) / "Artifacts.base"
            self.assertIn('file.hasProperty("artifacts")', f.read_text())
            f.write_text("mine\n")
            self.assertFalse(vault_write.ensure_artifacts_base(Path(t)))
            self.assertEqual(f.read_text(), "mine\n")


class ArchivePrefixTests(unittest.TestCase):
    def test_artifacts_prefix(self):
        self.assertIn("ARTIFACTS", archive.PREFIXES)
        self.assertTrue(archive.SESSION_FILE_RE.match("ARTIFACTS_2026-01-01-1200.md"))


if __name__ == "__main__":
    unittest.main()
