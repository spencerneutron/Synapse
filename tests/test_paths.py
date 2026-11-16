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

    def test_a_worktree_is_its_repository_project(self):
        repo = self.tmp / "work" / "Synapse"
        (repo / ".git" / "worktrees" / "fix-1").mkdir(parents=True)
        tree = self.tmp / "trees" / "fix-1"
        tree.mkdir(parents=True)
        (tree / ".git").write_text(f"gitdir: {(repo / '.git' / 'worktrees' / 'fix-1').as_posix()}\n")
        self.assertEqual(paths.resolve(cwd=tree).project, "Synapse")
        bare = self.tmp / "srv" / "api.git"
        (bare / "worktrees" / "main").mkdir(parents=True)
        (tree / ".git").write_text(f"gitdir: {(bare / 'worktrees' / 'main').as_posix()}\n")
        self.assertEqual(paths.resolve(cwd=tree).project, "api")
        (tree / ".git").write_text("gitdir: ../../work/Synapse/.git/modules/lib\n")   # a submodule
        self.assertEqual(paths.resolve(cwd=tree).project, "fix-1")

    def test_synapse_vault_drops_the_configured_vault_path(self):
        self.write_config('[stores.main]\nvault = "Synapse"\nvault_path = "%s"\n' % self.tmp.as_posix())
        self.assertEqual(paths.resolve(cwd=self.project).vault_path, self.tmp)
        os.environ["SYNAPSE_VAULT"] = "Other"
        try:
            r = paths.resolve(cwd=self.project)
        finally:
            os.environ.pop("SYNAPSE_VAULT")
        self.assertEqual((r.vault, r.vault_path), ("Other", None))

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


class WorkRootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "proj"
        (self.root / "src" / "deep").mkdir(parents=True)

    def test_legacy_current_resolves_as_before(self):
        cur = paths.work_dir(self.root)
        cur.mkdir(parents=True)
        deep = self.root / "src" / "deep"
        self.assertEqual(paths.find_work_dir(deep), cur)
        self.assertEqual(paths.work_root(deep), self.root)
        self.assertEqual(paths.find_work_dir(deep, session_id="s1"), cur)

    def test_no_work_folder_returns_start(self):
        deep = self.root / "src" / "deep"
        self.assertIsNone(paths.work_root(deep))
        self.assertEqual(paths.find_work_dir(deep), paths.work_dir(deep))

    def test_efforts_without_current(self):
        paths.efforts_dir(self.root).mkdir(parents=True)
        deep = self.root / "src" / "deep"
        self.assertEqual(paths.work_root(deep), self.root)
        self.assertEqual(paths.find_work_dir(deep), paths.work_dir(self.root))   # does not exist; callers cope
        self.assertEqual(paths.find_work_dir(deep, effort="a"), paths.effort_dir(self.root, "a"))

    def test_stops_at_git(self):
        (self.root / "src" / ".git").mkdir()
        paths.work_dir(self.root).mkdir(parents=True)
        self.assertIsNone(paths.work_root(self.root / "src" / "deep"))

    def test_auto_archive_state_per_effort(self):
        r = paths.resolve(cwd=self.root)
        self.assertEqual(paths.auto_archive_state(r, "s-1").name, "s-1.json")
        self.assertEqual(paths.auto_archive_state(r, "s-1", "alpha").name, "s-1--alpha.json")


class SiblingRootsTests(unittest.TestCase):
    def test_submodule_git_file_has_no_siblings(self):
        with tempfile.TemporaryDirectory() as t:
            top = Path(t).resolve() / "super"
            sub = top / "sub"
            (top / ".git" / "modules" / "sub").mkdir(parents=True)
            sub.mkdir()
            (sub / ".git").write_text("gitdir: ../.git/modules/sub\n")
            self.assertEqual(paths.sibling_roots(sub), [])

    def test_linked_worktree_git_file_still_finds_main(self):
        with tempfile.TemporaryDirectory() as t:
            main = Path(t).resolve() / "main"
            wt = Path(t).resolve() / "wt"
            (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
            wt.mkdir()
            (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'wt'}\n")
            self.assertEqual(paths.sibling_roots(wt), [main])


class SlugTests(unittest.TestCase):
    def test_valid_slug_table(self):
        good = ["a", "alpha", "auth-token-rotation", "a1", "1a", "x" * 40, "v2x", "version"]
        bad = ["", "-a", "a-", "A", "a_b", "a b", "a/b", "x" * 41, "con", "nul", "com1", "lpt9",
               "v2", "alpha-v2", "a-v10", "..", "caf\u00e9"]
        for s in good:
            self.assertTrue(paths.valid_slug(s), s)
        for s in bad:
            self.assertFalse(paths.valid_slug(s), s)
        self.assertFalse(paths.valid_slug(None))


if __name__ == "__main__":
    unittest.main()
