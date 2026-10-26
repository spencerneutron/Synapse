import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import helpers  # noqa: F401  (isolated SYNAPSE_HOME)
import archive
import extract
import migrate


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        os.environ["SYNAPSE_HOME"] = str(self.tmp / "home")
        self.work = self.tmp / "proj"
        current = self.work / ".claude-work" / "current"
        current.mkdir(parents=True)
        (current / "PLAN.md").write_text("# PLAN\n")
        (current / "EXECUTION.md").write_text("# EXECUTION\n")

    def run_archive(self, *args) -> dict:
        buf = StringIO()
        with redirect_stdout(buf):
            self.assertEqual(archive.main(["--workdir", str(self.work), *args]), 0)
        return json.loads(buf.getvalue())

    def test_copies_and_suffixes(self):
        first = self.run_archive("--id", "2026-10-26-1400")
        self.assertEqual(first["session_id"], "2026-10-26-1400")
        self.assertEqual(first["project"], "proj")
        self.assertEqual(len(first["copied"]), 2)
        self.assertTrue((self.work / ".claude-work" / "current" / "PLAN.md").exists())
        second = self.run_archive("--id", "2026-10-26-1400")
        self.assertEqual(second["session_id"], "2026-10-26-1400-v2")
        self.assertTrue(second["notes_path"].endswith("NOTES_2026-10-26-1400-v2.md"))

    def test_rejects_unsafe_ids(self):
        with self.assertRaises(SystemExit):
            archive.main(["--workdir", str(self.work), "--id", "../escape"])


class MigrateTests(unittest.TestCase):
    def test_portable_path_rewrites_v1_forms(self):
        cases = {
            ".claude-work/archive/PLAN_1.md": "archive/App/PLAN_1.md",
            "Veil/.claude-work/archive/PLAN_1.md": "archive/App/PLAN_1.md",
            "/home/u/ws/.claude-work/archive/PLAN_1.md": "archive/App/PLAN_1.md",
            "C:\\ws\\.claude-work\\archive\\PLAN_1.md": "archive/App/PLAN_1.md",
            "/home/u/Vaults/Synapse/Decisions/Use X.md": "vault/Decisions/Use X.md",
            "notes/other.md": "notes/other.md",
        }
        for old, new in cases.items():
            self.assertEqual(migrate.portable_path(old, "App"), new, old)

    def test_hash_matches_extractor(self):
        chunk = extract.Chunk(text="[PLAN > Goals]\nship it", source_path="archive/App/PLAN_1.md",
                              source_type="archive", session_id="1", project="App",
                              chunk_index=3, metadata={})
        self.assertEqual(migrate.chunk_hash(chunk.source_path, 3, chunk.text), chunk.hash())


if __name__ == "__main__":
    unittest.main()
