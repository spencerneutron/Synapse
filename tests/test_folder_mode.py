"""Folder mode: a store keeps its notes in a plain folder (notes = "folder")
and the obsidian CLI is never invoked."""

import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolated SYNAPSE_HOME)
import doctor
import extract
import paths
import setup_cmd
import vault_write

SPEC = "---\ntype: decision\ntitle: Use folders\nproject: demo\n---\n## Context\nx\n"
REAL_RUN_OBSIDIAN = vault_write.run_obsidian
BOOM = AssertionError("the obsidian CLI was reached in folder mode")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        env = mock.patch.dict(os.environ, {"SYNAPSE_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        for var in ("SYNAPSE_STORE", "SYNAPSE_VAULT"):
            os.environ.pop(var, None)
        self.addCleanup(os.chdir, os.getcwd())
        self.cwd = self.tmp / "repo"
        self.cwd.mkdir()
        os.chdir(self.cwd)

    def config(self, text):
        (self.home / "config.toml").write_text(text, encoding="utf-8")

    def folder_config(self, extra=""):
        self.config(f'[stores.main]\nnotes = "folder"\n{extra}')


class ResolveTests(Base):
    def test_default_is_obsidian_without_vault_path(self):
        r = paths.resolve()
        self.assertEqual((r.notes, r.vault_path), ("obsidian", None))
        self.assertEqual(r.as_dict()["notes"], "obsidian")

    def test_folder_defaults_to_store_vault(self):
        self.folder_config()
        r = paths.resolve()
        self.assertEqual(r.notes, "folder")
        self.assertEqual(r.vault_path, r.store_path / "vault")

    def test_explicit_vault_path_kept(self):
        self.folder_config(f'vault_path = "{(self.tmp / "n").as_posix()}"\n')
        self.assertEqual(paths.resolve().vault_path, self.tmp / "n")

    def test_invalid_value_exits(self):
        self.config('[stores.main]\nnotes = "notion"\n')
        with self.assertRaises(SystemExit) as cm:
            paths.resolve()
        msg = str(cm.exception.code)
        for part in ("'main'", "'notion'", "obsidian", "folder", "config.toml"):
            self.assertIn(part, msg)

    def test_synapse_vault_does_not_clear_folder(self):
        self.folder_config()
        with mock.patch.dict(os.environ, {"SYNAPSE_VAULT": "Other"}):
            r = paths.resolve()
        self.assertEqual(r.vault_path, r.store_path / "vault")

    def test_stored_paths(self):
        self.folder_config()
        r = paths.resolve()
        note = r.vault_path / "Decisions" / "x.md"
        self.assertEqual(paths.to_stored_path(note, r), "vault/Decisions/x.md")
        self.assertEqual(paths.to_display_path("vault/Decisions/x.md", r), str(note))
        custom = dataclasses.replace(r, vault_path=r.store_path / "notes")
        note = custom.vault_path / "Decisions" / "x.md"
        self.assertEqual(paths.to_stored_path(note, custom), "vault/Decisions/x.md")
        self.assertEqual(paths.to_display_path("vault/Decisions/x.md", custom), str(note))


class NoObsidianBase(Base):
    """Folder mode with every road to Obsidian booby-trapped."""

    def setUp(self):
        super().setUp()
        self.folder_config()
        self.r = paths.resolve()
        patches = [
            mock.patch.object(vault_write, "run_obsidian", side_effect=BOOM),
            mock.patch.object(vault_write, "ensure_obsidian_running", side_effect=BOOM),
            mock.patch.object(doctor, "obsidian_vaults", side_effect=BOOM),
            mock.patch.object(shutil, "which", return_value=None),
            mock.patch.object(vault_write, "VAULT_DIR", self.r.vault_path),
            mock.patch.object(vault_write, "VAULT_NAME", self.r.vault),
            mock.patch.object(vault_write, "NOTES_MODE", "folder"),
            mock.patch.object(vault_write, "_vault_path_cache", None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, argv):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = vault_write.main(argv)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def verify(self):
        code, out, _ = self.run_main(["verify"])
        self.assertEqual(code, 0, out)
        return out


class FolderModeTests(NoObsidianBase):
    def test_verify_creates_default_folder_and_subfolders(self):
        out = self.verify()
        self.assertIn(str(self.r.vault_path), out)
        for name in vault_write.FOLDERS.values():
            self.assertTrue((self.r.vault_path / name).is_dir())
        self.assertEqual(vault_write.vault_path(), self.r.vault_path)
        self.assertFalse((self.r.vault_path / vault_write.ARTIFACTS_BASE_NAME).exists())

    def test_verify_keeps_existing_notes(self):
        self.verify()
        keep = self.r.vault_path / "Facts" / "a.md"
        keep.write_text("mine", encoding="utf-8")
        self.verify()
        self.assertEqual(keep.read_text(encoding="utf-8"), "mine")

    def test_verify_refuses_a_missing_custom_folder(self):
        gone = self.tmp / "elsewhere"
        with mock.patch.object(vault_write, "VAULT_DIR", gone), self.assertRaises(SystemExit) as cm:
            vault_write.cmd_verify(Namespace())
        self.assertIn("vault_path", str(cm.exception.code))
        self.assertFalse(gone.exists())

    def test_verify_refuses_a_relative_path(self):
        with mock.patch.object(vault_write, "VAULT_DIR", Path("rel")), self.assertRaises(SystemExit) as cm:
            vault_write.cmd_verify(Namespace())
        self.assertIn("absolute", str(cm.exception.code))

    def test_create_note_and_note_exists(self):
        self.verify()
        spec = self.tmp / "spec.md"
        spec.write_text(SPEC, encoding="utf-8")
        code, out, _ = self.run_main(["create-note", "--from-md", str(spec)])
        self.assertEqual(code, 0)
        self.assertTrue((self.r.vault_path / "Decisions" / "Use folders.md").is_file())
        self.assertEqual(json.loads(out)["vault_relative_path"], "Decisions/Use folders.md")
        self.assertEqual(self.run_main(["note-exists", "Decisions", "Use folders"])[0], 0)
        self.assertEqual(self.run_main(["note-exists", "Decisions", "Nope"])[0], 1)

    def test_search_points_to_recall(self):
        code, out, err = self.run_main(["search", "sqlite vec"])
        self.assertEqual(code, 1)
        self.assertIn('synapse recall "sqlite vec"', err)

    def test_run_obsidian_refuses(self):
        with mock.patch.object(vault_write, "run_obsidian", REAL_RUN_OBSIDIAN), \
             self.assertRaises(SystemExit) as cm:
            vault_write.run_obsidian("vault", "info=path")
        self.assertIn("plain folder", str(cm.exception.code))

    def test_artifacts_base_writes_nothing(self):
        self.verify()
        self.assertFalse(vault_write.ensure_artifacts_base(self.r.vault_path))
        self.assertEqual(list(self.r.vault_path.glob("*.base")), [])

    def test_extract_resolves_notes_without_the_cli(self):
        self.verify()
        note = self.r.vault_path / "Patterns" / "P.md"
        note.write_text("x", encoding="utf-8")
        self.assertEqual(extract.note_file("Patterns/P.md", self.r), note)
        self.assertEqual(extract.note_file("vault/Patterns/P.md", self.r), note)

    def test_missing_note_with_vault_dir_unset_is_reported_missing(self):
        with mock.patch.object(vault_write, "VAULT_DIR", None):
            self.assertIsNone(vault_write.VAULT_DIR)
            self.assertEqual(extract.note_file("Patterns/Gone.md", self.r),
                             self.r.vault_path / "Patterns" / "Gone.md")
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as cm:
                extract.main(["embed-note", "Patterns/Gone.md"])
        msg = str(cm.exception.code)
        self.assertNotIn("has no folder", msg)
        self.assertIn("not found", msg)
        self.assertIn("Gone.md", msg)

    def test_to_stored_path_picks_the_deeper_root(self):
        store = self.r.store_path
        inside = dataclasses.replace(self.r, vault_path=store)   # store inside the vault folder
        self.assertEqual(paths.to_stored_path(store / "archive" / "p" / "s.md", inside), "archive/p/s.md")
        self.assertEqual(paths.to_stored_path(store / "vault" / "Facts" / "a.md", self.r), "vault/Facts/a.md")
        wide = dataclasses.replace(self.r, vault_path=store.parent)
        self.assertEqual(paths.to_stored_path(store / "archive" / "p" / "s.md", wide), "archive/p/s.md")

    def test_verify_message_for_missing_default_folder(self):
        gone = self.tmp / "gone"
        with mock.patch.object(vault_write, "VAULT_DIR", gone), \
             mock.patch.object(vault_write, "_vault_path_cache", None), self.assertRaises(SystemExit) as cm:
            vault_write.vault_path()
        self.assertIn("synapse vault verify", str(cm.exception.code))

    def test_doctor_notes_check(self):
        rep = doctor.Report()
        doctor.check_runtime(rep, self.r)   # folder missing: error
        notes = [i for i in rep.items if i["check"] == "notes"]
        self.assertEqual([i["level"] for i in notes], ["error"])
        self.assertIn("synapse vault verify", notes[0]["fix"])
        (self.r.vault_path / "Decisions").mkdir(parents=True)
        rep = doctor.Report()
        doctor.check_runtime(rep, self.r)
        self.assertEqual([i["level"] for i in rep.items if i["check"] == "notes"], ["warn"])
        self.verify()
        rep = doctor.Report()
        doctor.check_runtime(rep, self.r)
        notes = [i for i in rep.items if i["check"] == "notes"]
        self.assertEqual([i["level"] for i in notes], ["ok"])
        self.assertFalse([i for i in rep.items if i["check"] in ("obsidian", "vault")])


class SetupTests(Base):
    def run_setup(self, argv, which=None, config_file=None, tty=False):
        ok = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        out = StringIO()
        cfg_file = config_file or (self.tmp / "no-obsidian.json")
        with mock.patch.object(setup_cmd.subprocess, "run", return_value=ok), \
             mock.patch.object(doctor, "check_ollama", return_value=(True, True)), \
             mock.patch.object(setup_cmd, "autocompact_advice"), \
             mock.patch.object(shutil, "which", return_value=which), \
             mock.patch.object(doctor, "obsidian_config_file", return_value=cfg_file), \
             mock.patch.object(setup_cmd.sys.stdin, "isatty", return_value=tty), \
             redirect_stdout(out):
            code = setup_cmd.main(argv)
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def test_detects_folder_without_obsidian(self):
        with mock.patch.object(doctor, "obsidian_vaults", side_effect=BOOM):
            out = self.run_setup([])
        text = (self.home / "config.toml").read_text(encoding="utf-8")
        self.assertIn('notes = "folder"', text)
        self.assertNotIn("vault_path =", text.replace("# vault_path", ""))
        self.assertNotIn("Obsidian", out.replace("Obsidian-only", ""))
        self.assertNotIn("still needed for memory features:\n  - enable Obsidian", out)
        vault = self.home / "stores" / "main" / "vault"
        for name in paths.VAULT_FOLDERS:
            self.assertTrue((vault / name).is_dir())

    def test_relative_vault_path_creates_nothing(self):
        self.folder_config('vault_path = "rel-notes"\n')
        out = self.run_setup([])
        self.assertFalse((self.cwd / "rel-notes").exists())
        self.assertIn("make vault_path absolute under [stores.main]", out)

    def test_detects_obsidian_when_installed(self):
        cfg = self.tmp / "obsidian.json"
        cfg.write_text("{}", encoding="utf-8")
        self.run_setup([], config_file=cfg)
        self.assertIn('notes = "obsidian"', (self.home / "config.toml").read_text(encoding="utf-8"))

    def test_flag_obsidian_keeps_todo_lines(self):
        out = self.run_setup(["--notes", "obsidian"])
        self.assertIn('notes = "obsidian"', (self.home / "config.toml").read_text(encoding="utf-8"))
        self.assertIn("enable Obsidian's command-line interface", out)
        self.assertIn("create or open an Obsidian vault named 'Synapse'", out)

    def test_flag_folder_beats_detection(self):
        self.run_setup(["--notes", "folder"], which="/usr/bin/obsidian")
        self.assertIn('notes = "folder"', (self.home / "config.toml").read_text(encoding="utf-8"))

    def test_prompt_on_a_terminal(self):
        with mock.patch("builtins.input", return_value="folder") as ask:
            self.run_setup([], which="/usr/bin/obsidian", tty=True)
        self.assertIn("default: obsidian", ask.call_args[0][0])
        self.assertIn('notes = "folder"', (self.home / "config.toml").read_text(encoding="utf-8"))

    def test_existing_config_is_not_changed(self):
        self.config('[stores.main]\nnotes = "obsidian"\n')
        before = (self.home / "config.toml").read_text(encoding="utf-8")
        out = self.run_setup(["--notes", "folder"])
        self.assertEqual((self.home / "config.toml").read_text(encoding="utf-8"), before)
        self.assertIn('set notes = "folder" under [stores.main]', out)


if __name__ == "__main__":
    unittest.main()
