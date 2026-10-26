import json
import shutil
import subprocess
import sys
import unittest

from helpers import ROOT

HOOK = ROOT / "hooks" / "emission_check.py"


def run_hook(event) -> str:
    data = event if isinstance(event, bytes) else json.dumps(event).encode()
    out = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.decode().strip()


def blocks(message: str, **extra) -> bool:
    return bool(run_hook({"last_assistant_message": message, **extra}))


class EmissionCheckTests(unittest.TestCase):
    def test_blocks_each_mechanical_rule(self):
        self.assertTrue(blocks("Great question! Fixed it."))
        self.assertTrue(blocks("Sure! Done."))
        self.assertTrue(blocks("Fixed.\n\nLet me know if you need more."))
        self.assertTrue(blocks("Let us delve into the logs."))
        self.assertTrue(blocks("It's worth noting the build is slow."))
        self.assertTrue(blocks("Build passed ✅"))

    def test_reason_names_the_problems(self):
        out = json.loads(run_hook({"last_assistant_message": "Great question!\n\nHope this helps!"}))
        self.assertEqual(out["decision"], "block")
        self.assertIn("opens with praise", out["reason"])
        self.assertIn("pleasantry", out["reason"])

    def test_allows_clean_and_edge_cases(self):
        self.assertFalse(blocks("Fixed: the test used UTC. `x.swift:88` uses the device zone."))
        self.assertFalse(blocks("Tests pass.\nSure, the build is slow, but it finishes."))
        self.assertFalse(blocks("Renamed it.\n\n~~~\n# delve into tapestry\n~~~"))
        self.assertFalse(blocks("Renamed it.\n\n```\nlet me know if\n```"))
        self.assertFalse(blocks("> Let me know if\n\nQuoted above; nothing to fix."))
        self.assertFalse(blocks("Attach Delve to the Go process; Apache Tapestry is unaffected."))

    def test_guard_and_fail_open(self):
        self.assertFalse(blocks("Great question!", stop_hook_active=True))
        self.assertEqual(run_hook(b"not json"), "")
        self.assertEqual(run_hook({"last_assistant_message": ""}), "")

    def test_utf8_bytes(self):
        raw = '{"last_assistant_message": "Build failed ❌ on step 2."}'.encode("utf-8")
        self.assertTrue(run_hook(raw))


@unittest.skipUnless(shutil.which("bash"), "bash not available")
class SessionStartTests(unittest.TestCase):
    def test_core_payload(self):
        out = subprocess.run(["bash", str(ROOT / "hooks" / "session_start.sh"), "core"],
                             capture_output=True, check=True)
        payload = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "SessionStart")
        self.assertTrue(payload["additionalContext"].startswith("# Synapse rules"))

    def test_unknown_argument_prints_nothing(self):
        out = subprocess.run(["bash", str(ROOT / "hooks" / "session_start.sh"), "nope"],
                             capture_output=True, check=True)
        self.assertEqual(out.stdout, b"")


class ContextBuildTests(unittest.TestCase):
    def test_payloads_current_and_under_cap(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "build_context.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
