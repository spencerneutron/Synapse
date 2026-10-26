import os
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (isolated SYNAPSE_HOME)
import paths


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        os.environ["SYNAPSE_HOME"] = str(self.home)
        os.environ.pop("SYNAPSE_STORE", None)
        os.environ.pop("SYNAPSE_VAULT", None)
        self.project = self.tmp / "work" / "billing-api"
        (self.project / "src").mkdir(parents=True)

    def write_config(self, text):
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "config.toml").write_text(text)

    def test_defaults_without_config(self):
        r = paths.resolve(cwd=self.project)
        self.assertEqual(r.store, "main")
        self.assertEqual(r.store_path, self.home / "stores" / "main")
        self.assertEqual(r.vault, "Synapse")
        self.assertEqual(r.project, "billing-api")
        self.assertEqual(r.archive_dir, self.home / "stores" / "main" / "archive" / "billing-api")

    def test_git_root_names_the_project(self):
        (self.project / ".git").mkdir()
        r = paths.resolve(cwd=self.project / "src")
        self.assertEqual(r.project, "billing-api")
        self.assertEqual(r.project_source, "git root")

    def test_marker_selects_store_and_project(self):
        self.write_config('default_store = "main"\n[stores.client]\npath = "%s"\nvault = "Client"\n'
                          % (self.tmp / "client-store").as_posix())
        (self.project / ".synapse.toml").write_text('store = "client"\nproject = "billing"\n')
        r = paths.resolve(cwd=self.project / "src")
        self.assertEqual((r.store, r.vault, r.project), ("client", "Client", "billing"))
        self.assertEqual(r.db, self.tmp / "client-store" / "vectors.db")

    def test_env_beats_marker(self):
        self.write_config('[stores.a]\nvault = "A"\n[stores.b]\nvault = "B"\n')
        (self.project / ".synapse.toml").write_text('store = "a"\n')
        os.environ["SYNAPSE_STORE"] = "b"
        try:
            self.assertEqual(paths.resolve(cwd=self.project).store, "b")
        finally:
            del os.environ["SYNAPSE_STORE"]

    def test_unknown_store_fails_loudly(self):
        (self.project / ".synapse.toml").write_text('store = "nope"\n')
        with self.assertRaises(SystemExit):
            paths.resolve(cwd=self.project)

    def test_claude_config_dir_moves_home(self):
        del os.environ["SYNAPSE_HOME"]
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.tmp / "cfg")
        try:
            self.assertEqual(paths.home(), self.tmp / "cfg" / "synapse")
        finally:
            del os.environ["CLAUDE_CONFIG_DIR"]
            os.environ["SYNAPSE_HOME"] = str(self.home)

    def test_configured_stores_cover_config_and_default(self):
        self.write_config('default_store = "work"\n[stores.work]\n[stores.client]\npath = "%s"\n'
                          % (self.tmp / "c").as_posix())
        stores = paths.configured_stores()
        self.assertEqual(set(stores), {"work", "client"})
        self.assertEqual(stores["work"], self.home / "stores" / "work")
        self.assertEqual(stores["client"], self.tmp / "c")

    def test_project_names_are_folder_safe(self):
        self.assertEqual(paths.safe_project('a/b:c*'), "a-b-c-")
        self.assertEqual(paths.safe_project("  "), "unsorted")

    def test_stored_paths_are_portable(self):
        r = paths.resolve(cwd=self.project)
        archived = r.archive_dir / "PLAN_2026-10-26-1400.md"
        self.assertEqual(paths.to_stored_path(archived, r), "archive/billing-api/PLAN_2026-10-26-1400.md")
        note = Path("/any/where/Vault/Decisions/Use X.md")
        self.assertEqual(paths.to_stored_path(note, r), "vault/Decisions/Use X.md")
        self.assertEqual(paths.to_display_path("archive/billing-api/x.md", r), str(r.store_path / "archive/billing-api/x.md"))


if __name__ == "__main__":
    unittest.main()
