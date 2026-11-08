import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolates SYNAPSE_HOME, sets sys.path)
import doctor


class DoctorNamesakeTests(unittest.TestCase):
    def run_check(self, settings=None, installed=None, raw=None):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            home = t / "home"
            (home / "plugins").mkdir(parents=True)
            if settings is not None:
                (home / "settings.json").write_text(raw or json.dumps(settings))
            if installed is not None:
                (home / "plugins" / "installed_plugins.json").write_text(
                    raw or json.dumps({"plugins": installed}))
            rep = doctor.Report()
            with mock.patch.object(doctor, "claude_dir", return_value=home):
                doctor.check_namesake(rep, t)
            return [i for i in rep.items if i["check"] == "namesake"]

    def test_ours_only_is_silent(self):
        self.assertEqual(self.run_check({"enabledPlugins": {"synapse@synapse": True}},
                                        {"synapse@synapse": [{}]}), [])

    def test_enabled_life_sciences_warns(self):
        found = self.run_check({"enabledPlugins": {"synapse@life-sciences": True,
                                                   "synapse@synapse": True}})
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["level"], "warn")
        self.assertIn("synapse@life-sciences", found[0]["detail"])
        self.assertIn("claude plugin uninstall synapse@life-sciences", found[0]["fix"])

    def test_installed_only_warns(self):
        found = self.run_check(installed={"synapse@life-sciences": [{}]})
        self.assertEqual(len(found), 1, found)

    def test_disabled_entry_is_silent(self):
        self.assertEqual(self.run_check({"enabledPlugins": {"synapse@life-sciences": False}}), [])

    def test_malformed_json_is_silent(self):
        self.assertEqual(self.run_check(settings={}, raw="{not json"), [])
        self.assertEqual(self.run_check(installed={}, raw="[1,"), [])

    def test_missing_files_are_silent(self):
        self.assertEqual(self.run_check(), [])


if __name__ == "__main__":
    unittest.main()
