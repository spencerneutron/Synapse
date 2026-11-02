"""The vault and recall CLI surfaces that agents call during extraction:
Markdown note specs, JSON errors, note paths, the Obsidian launch, and
argument parsing."""

import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

from helpers import LIB
import extract
import paths
import vault_write


SPEC_MD = """---
type: pattern
title: Quote Windows paths in Git Bash
project: synapse
session_id: 2026-11-02-1200
tags: [pattern, windows]
related: ["[[2026-11-02-1200]]", [[Earlier note]]]
sources:
  - "[[2026-11-02-1200]]"
applies_to: [windows, shell]
---
# Pattern: Quote Windows paths in Git Bash

## Problem
Paths such as %LOCALAPPDATA%\\az-admin and C:\\new\\tools break JSON.
"""


class MarkdownSpecTests(unittest.TestCase):
    def test_fields_lists_and_literal_backslashes(self):
        spec = vault_write.parse_md_spec(SPEC_MD)
        self.assertEqual(spec["type"], "pattern")
        self.assertEqual(spec["session_id"], "2026-11-02-1200")
        self.assertEqual(spec["tags"], ["pattern", "windows"])
        self.assertEqual(spec["related"], ["[[2026-11-02-1200]]", "[[Earlier note]]"])
        self.assertEqual(spec["sources"], ["[[2026-11-02-1200]]"])
        self.assertEqual(spec["applies_to"], ["windows", "shell"])
        self.assertIn(r"%LOCALAPPDATA%\az-admin and C:\new\tools", spec["body"])

    def test_generated_h1_is_not_doubled(self):
        spec = vault_write.parse_md_spec(SPEC_MD)
        self.assertTrue(spec["body"].startswith("\n## Problem") or spec["body"].startswith("## Problem"))
        content = vault_write.build_note_content(spec)
        self.assertEqual(content.count("# Pattern: Quote Windows paths in Git Bash"), 1)

    def test_bare_wikilinks_and_scalars(self):
        spec = vault_write.parse_md_spec(
            "---\r\ntype: decision\r\ntitle: 'Use B'\r\nsupersedes: [[Use A]]\r\n"
            "related: [[x]], [[y]]\r\nsources:\r\n---\r\nBody\r\n")
        self.assertEqual(spec["title"], "Use B")
        self.assertEqual(spec["supersedes"], "[[Use A]]")
        self.assertEqual(spec["related"], ["[[x]]", "[[y]]"])
        self.assertEqual(spec["sources"], [])
        self.assertEqual(spec["body"], "Body\n")

    def test_apostrophes_quotes_and_loose_layout(self):
        spec = vault_write.parse_md_spec(
            "\n---  \ntype: pattern\ntitle: \"Say \\\"hi\\\" at C:\\Users\"\n"
            "related: [[[Don't use A]], [[B]]]\napplies_to: [git bash, user's shell, 'it''s']\n"
            "---\n# Say \"hi\" at C:\\Users\nBody\n")
        self.assertEqual(spec["title"], 'Say "hi" at C:\\Users')
        self.assertEqual(spec["related"], ["[[Don't use A]]", "[[B]]"])
        self.assertEqual(spec["applies_to"], ["git bash", "user's shell", "it's"])
        self.assertEqual(spec["body"], "Body\n")   # an H1 without the type prefix is dropped too

    def test_errors_name_the_problem(self):
        with self.assertRaisesRegex(ValueError, "no front matter"):
            vault_write.parse_md_spec("## Problem\nno fields\n")
        with self.assertRaisesRegex(ValueError, "cannot read"):
            vault_write.parse_md_spec("---\ntype: pattern\njust words\n---\nbody\n")


class CreateNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = vault_write.vault_path
        vault_write.vault_path = lambda: self.tmp / "vault"

    def tearDown(self):
        vault_write.vault_path = self.saved

    def create(self, **kw) -> dict:
        args = Namespace(**{"from_md": None, "from_file": None, "on_conflict": "error", **kw})
        with redirect_stdout(StringIO()) as out:
            vault_write.cmd_create_note(args)
        return json.loads(out.getvalue())

    def test_from_md_writes_the_note_and_prints_forward_slashes(self):
        src = self.tmp / "spec.md"
        src.write_text(SPEC_MD, encoding="utf-8")
        report = self.create(from_md=str(src))
        self.assertEqual(report["vault_relative_path"], "Patterns/Quote Windows paths in Git Bash.md")
        self.assertNotIn("\\", report["path"])
        written = Path(report["path"]).read_text(encoding="utf-8")
        self.assertIn("applies_to: [windows, shell]", written)
        self.assertIn(r"C:\new\tools", written)

    def test_bad_json_escape_gets_a_hint(self):
        src = self.tmp / "spec.json"
        src.write_text('{"type": "pattern", "title": "T", "body": "C:\\Users\\me"}', encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.create(from_file=str(src))
        self.assertIn("Invalid \\escape", str(cm.exception.code))
        self.assertIn("--from-md", str(cm.exception.code))
        src.write_text('{"type": "pattern", "title": "T", "body": "C:\\users"}', encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            self.create(from_file=str(src))
        self.assertIn("--from-md", str(cm.exception.code))   # Invalid \uXXXX escape


class EmbedNotePathTests(unittest.TestCase):
    def test_vault_relative_paths_resolve_against_the_store_vault(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        r = dataclasses.replace(paths.resolve(), vault_path=tmp)
        expected = tmp / "Patterns" / "X.md"
        expected.parent.mkdir()
        expected.write_text("x")
        self.assertEqual(extract.note_file("Patterns/X.md", r), expected)
        self.assertEqual(extract.note_file("vault/Patterns/X.md", r), expected)
        self.assertEqual(extract.note_file("Patterns\\X.md", r), expected)
        absolute = tmp / "elsewhere.md"
        self.assertEqual(extract.note_file(str(absolute), r), absolute)
        self.assertEqual(extract.note_file("notes/x.md", r), Path("notes/x.md"))

    def test_a_note_missing_from_vault_path_is_looked_up_where_obsidian_wrote_it(self):
        configured, actual = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        for d in (configured, actual):
            self.addCleanup(shutil.rmtree, d, True)
        r = dataclasses.replace(paths.resolve(), vault_path=configured)
        with mock.patch.object(vault_write, "vault_path", lambda: actual):
            self.assertEqual(extract.note_file("Decisions/Y.md", r), actual / "Decisions" / "Y.md")

    def test_missing_notes_fail_before_any_embedding(self):
        with mock.patch.object(extract, "db_connect", side_effect=AssertionError("embedded")):
            with self.assertRaises(SystemExit) as cm:
                extract.cmd_embed_note(Namespace(paths=["/no/such/a.md", "/no/such/b.md"],
                                                 project=None, db=None))
        self.assertIn("a.md", str(cm.exception.code))
        self.assertIn("b.md", str(cm.exception.code))


class ObsidianLaunchTests(unittest.TestCase):
    def setUp(self):
        vault_write._obsidian_checked = False
        self.addCleanup(setattr, vault_write, "_obsidian_checked", False)
        self.calls = []

    def fake_run(self, running_after: int, tasklist_code: int = 0):
        def run(cmd, **kw):
            self.calls.append(cmd)
            if cmd[0] == "tasklist":
                n = sum(1 for c in self.calls if c[0] == "tasklist")
                # Console code page, not UTF-8 (German "ausgef\x81hrt", French NBSP 0xFF).
                out = b"Obsidian.exe  1234 Console  1\xff234 K" if n > running_after \
                    else b"INFORMATION: Es werden keine Tasks ausgef\x81hrt"
                return subprocess.CompletedProcess(cmd, tasklist_code, stdout=out)
            return subprocess.CompletedProcess(cmd, 1)   # explorer.exe exits 1 on success
        return run

    def test_windows_launches_detached_with_the_vault(self):
        with mock.patch.object(vault_write.sys, "platform", "win32"), \
             mock.patch.object(vault_write, "VAULT_NAME", "My Vault"), \
             mock.patch.object(vault_write.subprocess, "run", self.fake_run(running_after=2)), \
             mock.patch.object(vault_write.time, "sleep"), redirect_stdout(StringIO()), \
             mock.patch.object(sys, "stderr", StringIO()):
            vault_write.ensure_obsidian_running()
        launches = [c for c in self.calls if c[0] != "tasklist"]
        self.assertEqual(launches, [["explorer.exe", "obsidian://open?vault=My%20Vault"]])

    def test_windows_already_running_launches_nothing(self):
        with mock.patch.object(vault_write.sys, "platform", "win32"), \
             mock.patch.object(vault_write.subprocess, "run", self.fake_run(running_after=0)):
            vault_write.ensure_obsidian_running()
        self.assertEqual([c[0] for c in self.calls], ["tasklist"])

    def test_windows_check_that_cannot_run_launches_nothing(self):
        with mock.patch.object(vault_write.sys, "platform", "win32"), \
             mock.patch.object(vault_write.subprocess, "run", self.fake_run(0, tasklist_code=1)):
            vault_write.ensure_obsidian_running()
        self.assertEqual([c[0] for c in self.calls], ["tasklist"])

    def test_other_platforms_are_left_alone(self):
        with mock.patch.object(vault_write.sys, "platform", "linux"), \
             mock.patch.object(vault_write.subprocess, "run", side_effect=AssertionError("ran")):
            vault_write.ensure_obsidian_running()


class CommandLineTests(unittest.TestCase):
    def synapse(self, *argv) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(LIB / "cli.py"), *argv],
                              capture_output=True, text=True)

    def test_usage_names_the_synapse_command(self):
        out = self.synapse("recall", "q", "--no-such-flag")
        self.assertEqual(out.returncode, 2)
        self.assertTrue(out.stderr.startswith("usage: synapse recall"), out.stderr)
        self.assertIn("synapse recall: error:", out.stderr)
        out = self.synapse("extract", "embed-note")
        self.assertIn("usage: synapse extract embed-note", out.stderr)

    def test_recall_accepts_limit_and_n(self):
        for flag in ("--limit", "-n", "--top-k"):
            out = self.synapse("recall", "q", flag, "1")
            self.assertNotIn("unrecognized arguments", out.stderr, flag)
            self.assertIn("DB not found", out.stderr, flag)   # parsed; the test home has no DB


if __name__ == "__main__":
    unittest.main()
