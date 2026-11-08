import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import LIB, ROOT  # noqa: F401  (puts lib/synapse on sys.path)

import archive
import detach


class DetachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.home, self.proj = t / "home", t / "proj"
        (self.proj / ".claude-work" / "current").mkdir(parents=True)
        (self.proj / ".claude-work" / "current" / "PLAN.md").write_text("plan\n")
        (self.proj / ".claude-work" / "current" / "EXECUTION.md").write_text("exec\n")
        self.home.mkdir()
        env = {"SYNAPSE_HOME": str(self.home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for k in ("SYNAPSE_DETACHED", "SYNAPSE_PLUGIN_DIR", "SYNAPSE_STORE", "SYNAPSE_VAULT"):
            os.environ.pop(k, None)
        old = os.getcwd()
        self.addCleanup(os.chdir, old)

    def config(self, text):
        (self.home / "config.toml").write_text(text)

    def end(self, **ev):
        archive.auto_archive({"session_id": "s1", "cwd": str(self.proj), **ev})

    def test_spawns_after_archive(self):
        self.config("[extract]\non_exit = true\n")
        with mock.patch("detach.shutil.which", return_value="/bin/claude"), \
                mock.patch("detach.subprocess.Popen") as popen:
            self.end()
        popen.assert_called_once()
        argv = popen.call_args.args[0]
        kw = popen.call_args.kwargs
        self.assertEqual(argv[:2], ["/bin/claude", "-p"])
        self.assertRegex(argv[2], r"^/synapse:extract-session \d{4}-\d\d-\d\d-\d{4} --project proj")
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertIn('{"disableAllHooks":true}', argv)
        self.assertEqual(kw["env"]["SYNAPSE_DETACHED"], "1")
        self.assertTrue(kw["env"]["PATH"].startswith(str(ROOT / "bin")))
        self.assertTrue(os.path.samefile(kw["cwd"], self.proj))
        self.assertEqual(kw["stdin"], detach.subprocess.DEVNULL)
        self.assertTrue(kw["close_fds"])
        if os.name == "nt":
            self.assertIn("creationflags", kw)
        else:
            self.assertTrue(kw["start_new_session"])
        self.assertTrue((self.home / "state").is_dir())

    def test_plugin_dir_override(self):
        os.environ["SYNAPSE_PLUGIN_DIR"] = "/x/plugin"
        argv = detach.command("claude", "id1", "p")
        self.assertEqual(argv[-2:], ["--plugin-dir", "/x/plugin"])

    def test_not_spawned_when_off_by_default(self):
        with mock.patch("detach.shutil.which", return_value="/bin/claude"), \
                mock.patch("detach.subprocess.Popen") as popen:
            self.end()
        popen.assert_not_called()
        self.assertTrue(list((self.home / "stores").glob("main/archive/proj/PLAN_*.md")))

    def test_not_spawned_on_skip(self):
        self.config("[extract]\non_exit = true\n")
        with mock.patch("detach.shutil.which", return_value="/bin/claude"), \
                mock.patch("detach.subprocess.Popen") as popen:
            self.end()
            self.end()   # unchanged content: skipped
        popen.assert_called_once()

    def test_not_spawned_when_detached(self):
        self.config("[extract]\non_exit = true\n")
        os.environ["SYNAPSE_DETACHED"] = "1"
        with mock.patch("detach.shutil.which", return_value="/bin/claude"), \
                mock.patch("detach.subprocess.Popen") as popen:
            self.end()
        popen.assert_not_called()

    def test_missing_claude_is_silent(self):
        self.config("[extract]\non_exit = true\n")
        with mock.patch("detach.shutil.which", return_value=None), \
                mock.patch("detach.subprocess.Popen") as popen:
            self.end()
        popen.assert_not_called()

    def test_popen_failure_is_silent(self):
        self.config("[extract]\non_exit = true\n")
        with mock.patch("detach.shutil.which", return_value="/bin/claude"), \
                mock.patch("detach.subprocess.Popen", side_effect=OSError("no")):
            self.end()   # does not raise


if __name__ == "__main__":
    unittest.main()
