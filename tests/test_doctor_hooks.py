import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import doctor

HOOK = {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}


class DoctorPostToolUseTests(unittest.TestCase):
    def run_check(self, project=None, plugin_hooks=None):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / ".claude").mkdir()
            (t / "home").mkdir()
            if project is not None:
                (t / ".claude" / "settings.json").write_text(json.dumps(project))
            if plugin_hooks is not None:
                plug = t / "plug"
                (plug / "hooks").mkdir(parents=True)
                (plug / "hooks" / "hooks.json").write_text(json.dumps({"hooks": plugin_hooks}))
                (t / "home" / "settings.json").write_text(json.dumps({"enabledPlugins": {"other@m": True}}))
                (t / "home" / "plugins").mkdir()
                (t / "home" / "plugins" / "installed_plugins.json").write_text(json.dumps(
                    {"plugins": {"other@m": [{"installPath": str(plug)}]}}))
            rep = doctor.Report()
            with mock.patch.object(doctor, "claude_dir", return_value=t / "home"), \
                    mock.patch.object(doctor, "MANAGED_SETTINGS", {}):
                doctor.check_settings(rep, t)
            return [i for i in rep.items if i["check"] == "posttooluse-hooks"]

    def test_settings_layer_hook_is_info(self):
        found = self.run_check(project=HOOK)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["level"], "info")
        self.assertIn("echo hi", found[0]["detail"])

    def test_plugin_hook_is_info(self):
        found = self.run_check(plugin_hooks=HOOK["hooks"])
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["level"], "info")
        self.assertIn("other@m", found[0]["detail"])

    def test_no_hooks_no_rows(self):
        self.assertEqual(self.run_check(project={}), [])


if __name__ == "__main__":
    unittest.main()
