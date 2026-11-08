"""synapse setup --autocompact: writes settings.json safely; doctor reports the window."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (isolates SYNAPSE_HOME, sets sys.path)
import doctor
import setup_cmd


class AutocompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.cfg = self.home / ".claude"
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_AUTO_COMPACT_WINDOW", "ANTHROPIC_MODEL")}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), CLAUDE_CONFIG_DIR=str(self.cfg))
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        m = mock.patch.object(doctor, "MANAGED_SETTINGS", {})
        m.start()
        self.addCleanup(m.stop)
        self.settings = self.cfg / "settings.json"

    def run_setup(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = setup_cmd.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def backups(self):
        return sorted(self.cfg.glob("settings.json.synapse-backup-*"))

    def test_writes_keeps_keys_and_backs_up(self):
        self.cfg.mkdir()
        original = '{"model": "opus", "env": {"A": "1"}}'
        self.settings.write_text(original, encoding="utf-8")
        code, out, _ = self.run_setup("--autocompact", "300000")
        self.assertEqual(code, 0, out)
        data = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(data, {"model": "opus", "env": {"A": "1"}, "autoCompactWindow": 300000})
        self.assertTrue(self.settings.read_text(encoding="utf-8").endswith("}\n"))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.backups()[0].read_text(encoding="utf-8"), original)
        self.assertIn("autoCompactWindow: 300000", out)
        self.assertEqual(list(self.cfg.glob("*.tmp")), [])

    def test_creates_missing_file(self):
        code, _, _ = self.run_setup("--autocompact", "250000")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), {"autoCompactWindow": 250000})
        self.assertEqual(self.backups(), [])

    def test_k_suffix(self):
        self.assertEqual(setup_cmd.parse_window("300k"), 300000)
        self.assertEqual(setup_cmd.parse_window("300K"), 300000)
        self.run_setup("--autocompact", "300k")
        self.assertEqual(json.loads(self.settings.read_text())["autoCompactWindow"], 300000)

    def test_refuses_when_set_top_level(self):
        self.cfg.mkdir()
        text = '{"autoCompactWindow": 200000}'
        self.settings.write_text(text)
        code, _, err = self.run_setup("--autocompact", "300k")
        self.assertNotEqual(code, 0)
        self.assertIn("200000", err)
        self.assertEqual(self.settings.read_text(), text)
        self.assertEqual(self.backups(), [])

    def test_refuses_when_set_under_model_settings(self):
        self.cfg.mkdir()
        text = '{"modelSettings": {"opus": {"autoCompactWindow": 400000}}}'
        self.settings.write_text(text)
        code, _, err = self.run_setup("--autocompact", "300k")
        self.assertNotEqual(code, 0)
        self.assertIn("opus", err)
        self.assertIn("400000", err)
        self.assertEqual(self.settings.read_text(), text)

    def test_refuses_non_object_file(self):
        self.cfg.mkdir()
        self.settings.write_text("[1, 2]")
        code, _, _ = self.run_setup("--autocompact", "300k")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.settings.read_text(), "[1, 2]")

    def test_refuses_invalid_n(self):
        for bad in ("0", "-5", "abc", "1.5", "k", ""):
            code, _, err = self.run_setup("--autocompact", bad)
            self.assertNotEqual(code, 0, bad)
            self.assertFalse(self.settings.exists(), bad)

    def advice(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            setup_cmd.autocompact_advice()
        return out.getvalue()

    def test_advice_when_unset_not_when_set(self):
        self.assertIn("synapse setup --autocompact 300k", self.advice())
        self.cfg.mkdir()
        self.settings.write_text('{"autoCompactWindow": 300000}')
        self.assertEqual(self.advice(), "")

    def test_doctor_reports_top_level_and_per_model(self):
        self.cfg.mkdir()
        self.settings.write_text(json.dumps(
            {"autoCompactWindow": 300000, "modelSettings": {"opus": {"autoCompactWindow": 400000}}}))
        rep = doctor.Report()
        doctor.check_settings(rep, self.home)
        found = [i for i in rep.items if i["check"] == "autocompact-window"]
        self.assertEqual(len(found), 1)
        self.assertIn("300000 (top level", found[0]["detail"])
        self.assertIn("opus: 400000 (modelSettings", found[0]["detail"])


if __name__ == "__main__":
    unittest.main()
