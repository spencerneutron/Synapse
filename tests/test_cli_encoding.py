"""Every CLI usage/help text must reach a Windows pipe as strict UTF-8.

Windows Python writes pipes in the ANSI code page (cp1252) unless the module
reconfigures stdout first. A help text with an em dash then goes out as byte
0x97 and a UTF-8 reader fails. 2.5.1 and 2.6.0 each lost a CI run to this.
This test forces cp1252 with PYTHONIOENCODING and requires that stdout and
stderr decode as strict UTF-8 for every help and usage form.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "lib" / "synapse"
sys.path.insert(0, str(LIB))
import cli  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLI = LIB / "cli.py"

# Scripts that do not take --help: run them with no args and empty stdin.
# emission_check.py is a Stop hook; it reads event JSON from stdin and, on
# empty input, allows the stop without writing anything.
NO_HELP_SCRIPTS = {"emission_check.py"}
# Skip list (script name -> reason). Empty: every script runs safely here.
SKIP_SCRIPTS = {}

# No-arg forms that are safe to run: a usage text or usage error, no writes.
# Left out on purpose (they provision a venv or read/write a store):
# setup, doctor, archive, pending, facts, backfill, recall-hint.
NOARG_ALLOWLIST = {
    "recall", "recall-check", "compact-guide", "checkpoint",
    "share", "shared", "extract", "vault", "migrate", "where", "version",
}

SUBCOMMAND_GROUP = re.compile(r"\{([A-Za-z0-9_,-]+)\}")


def run(args, home, cwd):
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    env["SYNAPSE_HOME"] = home
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        env=env, cwd=cwd, input=b"", capture_output=True, timeout=60,
    )


class CliEncodingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.home = os.path.join(cls._tmp.name, "home")
        cls.cwd = os.path.join(cls._tmp.name, "cwd")
        os.makedirs(cls.home)
        os.makedirs(cls.cwd)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def check(self, args, must_exit_zero):
        proc = run(args, self.home, self.cwd)
        for name, data in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            try:
                data.decode("utf-8")
            except UnicodeDecodeError as exc:
                self.fail(f"{args}: {name} is not UTF-8: {exc}")
        if must_exit_zero:
            self.assertEqual(proc.returncode, 0, f"{args}: {proc.stderr[:300]!r}")
            self.assertTrue(proc.stdout.strip(), f"{args}: empty help output")
        else:
            self.assertIn(proc.returncode, (0, 1, 2), f"{args}: exit {proc.returncode}")
        return proc

    def test_top_level(self):
        for args in ([], ["help"], ["--help"], ["version"]):
            with self.subTest(args=args):
                self.check(args, must_exit_zero=True)

    def test_command_help(self):
        for cmd in [*cli.COMMANDS, "where"]:
            with self.subTest(cmd=cmd):
                self.check([cmd, "--help"], must_exit_zero=True)

    def test_command_no_args(self):
        self.assertLessEqual(NOARG_ALLOWLIST - {*cli.COMMANDS, "where", "version"}, set())
        for cmd in sorted(NOARG_ALLOWLIST):
            with self.subTest(cmd=cmd):
                self.check([cmd], must_exit_zero=False)

    def test_subcommand_help(self):
        seen = 0
        for cmd in cli.COMMANDS:
            parent = run([cmd, "--help"], self.home, self.cwd)
            text = parent.stdout.decode("utf-8", "replace")
            m = SUBCOMMAND_GROUP.search(text)
            if not m:
                continue
            for sub in m.group(1).split(","):
                seen += 1
                with self.subTest(cmd=cmd, sub=sub):
                    self.check([cmd, sub, "--help"], must_exit_zero=True)
        self.assertGreater(seen, 0, "no argparse subcommands discovered")


class ScriptEncodingTest(unittest.TestCase):
    """Directly-run scripts (tests and maintainers run them with `python file.py`)."""

    def test_scripts_emit_utf8(self):
        scripts = sorted([*(ROOT / "tools").glob("*.py"), *(ROOT / "hooks").glob("*.py")])
        self.assertGreater(len(scripts), 0, "no scripts discovered")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "home")
            cwd = os.path.join(tmp, "cwd")
            os.makedirs(home)
            os.makedirs(cwd)
            for script in scripts:
                if script.name in SKIP_SCRIPTS:
                    continue
                with self.subTest(script=f"{script.parent.name}/{script.name}"):
                    args = [] if script.name in NO_HELP_SCRIPTS else ["--help"]
                    env = dict(os.environ)
                    env.pop("PYTHONUTF8", None)
                    env["PYTHONIOENCODING"] = "cp1252"
                    env["SYNAPSE_HOME"] = home
                    proc = subprocess.run(
                        [sys.executable, str(script), *args],
                        env=env, cwd=cwd, input=b"", capture_output=True, timeout=60,
                    )
                    for name, data in (("stdout", proc.stdout), ("stderr", proc.stderr)):
                        try:
                            data.decode("utf-8")
                        except UnicodeDecodeError as exc:
                            self.fail(f"{script.name}: {name} is not UTF-8: {exc}")
                    self.assertIn(proc.returncode, (0, 1, 2),
                                  f"{script.name}: exit {proc.returncode}")


if __name__ == "__main__":
    unittest.main()
