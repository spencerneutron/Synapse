import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import ROOT

HOOK = ROOT / "hooks" / "emission_check.py"


def find_bash() -> str | None:
    """bash as Claude Code runs it: Git Bash on Windows, where System32's
    bash.exe is the WSL launcher and fails without a Linux distribution."""
    if sys.platform != "win32":
        return shutil.which("bash")
    candidates = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"]
    git = shutil.which("git")
    if git:
        candidates.insert(0, Path(git).resolve().parent.parent / "bin" / "bash.exe")
    return next((str(c) for c in candidates if c.exists()), None)


BASH = find_bash()


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
        self.assertTrue(blocks("Reply **yes**, **no**, or **skip <numbers>**."))
        self.assertTrue(blocks("Run it with <session-id> filled in."))

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
        self.assertFalse(blocks("Run `synapse recall <query>`; see <https://example.com> or <a@b.co>."))
        self.assertFalse(blocks("Pass when 1 < n and m > 2."))
        self.assertFalse(blocks("It returns List<String>, Promise<void>, or Vec<u8>; if a<b and c>d."))
        self.assertFalse(blocks("Press <Enter>. | one <br> two | a <kbd>Ctrl</kbd> key |"))

    def test_closer_recap(self):
        self.assertTrue(blocks("Fixed the regex.\n\nIn summary, the slug is clean now."))
        self.assertTrue(blocks("Fixed the regex.\n\nTo recap: two changes."))
        self.assertTrue(blocks("Fixed the regex.\n\nOverall, the change is small."))
        # Only at the start of the last paragraph, and "overall" needs its comma.
        self.assertFalse(blocks("In summary, three tests failed.\n\nAll pass now at `a.py:3`."))
        self.assertFalse(blocks("Fixed.\n\nOverall latency dropped from 90 ms to 40 ms."))

    def test_closer_offer(self):
        self.assertTrue(blocks("Fixed.\n\nI can also add tests."))
        self.assertTrue(blocks("Fixed.\n\nWould you like me to add tests?"))
        self.assertTrue(blocks("Fixed.\n\nWant me to open the PR?"))
        self.assertTrue(blocks("Fixed.\n\nShall I merge it?"))
        self.assertTrue(blocks("Fixed.\n\nI can fix the accent handling too if you'd like."))
        # Offers outside the last paragraph, and plain "I can" facts, pass.
        self.assertFalse(blocks("I can also reproduce it on 3.11.\n\nFixed in `a.py:3`."))
        self.assertFalse(blocks("Fixed.\n\nI can't run the GPU tests here: no CUDA device."))
        self.assertFalse(blocks("Fixed.\n\nMerge it now?"))
        self.assertFalse(blocks("Deployed.\n\nWhen you want me to check the result, start a new session."))

    def test_not_just_shape(self):
        self.assertTrue(blocks("It's not just a typo, it's a design flaw."))
        self.assertTrue(blocks("This is not only slow; it is wrong."))
        self.assertTrue(blocks("That's not merely a warning \u2014 it's a crash."))
        self.assertFalse(blocks("It's not just slow; the build fails at step 2."))
        self.assertFalse(blocks("It is not only the cache that grows."))

    def test_header_cap(self):
        heads = "".join(f"## Part {i}\nText {i}.\n\n" for i in range(4))
        self.assertTrue(blocks("Done.\n\n" + heads))
        self.assertFalse(blocks("Done.\n\n" + "".join(f"## Part {i}\nText {i}.\n\n" for i in range(3))))
        long_body = " ".join(["word"] * 520)
        self.assertFalse(blocks("Done.\n\n" + heads + long_body))
        self.assertFalse(blocks("Done.\n\n```\n# a\n# b\n# c\n# d\n```"))

    def test_reason_carries_the_contract(self):
        reason = json.loads(run_hook({"last_assistant_message": "Fixed.\n\nWant me to add tests?"}))["reason"]
        self.assertIn("ends with an offer", reason)
        for phrase in ("Lead with the outcome", "Report evidence, not effort", "Size to the ask",
                       "Specifics over adjectives", "End on substance", "Plain words"):
            self.assertIn(phrase, reason)
        self.assertNotIn("Load the", reason)
        self.assertNotIn("skill", reason)

    def test_directive_matches_skill(self):
        spec = json.loads((ROOT / "hooks" / "emission_patterns.json").read_text(encoding="utf-8"))
        skill = (ROOT / "skills" / "emission-contract" / "SKILL.md").read_text(encoding="utf-8")
        titles = [d.split(":")[0] for d in spec["directive"]]
        import re
        skill_titles = re.findall(r"^\d+\. \*\*(.+?)\.\*\*", skill, re.M)
        self.assertEqual(titles, skill_titles)

    def test_every_pattern_has_unique_id_and_message(self):
        spec = json.loads((ROOT / "hooks" / "emission_patterns.json").read_text(encoding="utf-8"))
        ids = [p["id"] for p in spec["patterns"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(p["message"] and p["where"] in ("start", "end", "anywhere") for p in spec["patterns"]))

    def test_fail_open_logs_to_stderr(self):
        out = subprocess.run([sys.executable, str(HOOK)], input=b"not json", capture_output=True)
        self.assertEqual(out.returncode, 0)
        self.assertEqual(out.stdout, b"")
        self.assertIn(b"emission_check: skipped (JSONDecodeError", out.stderr)

    def test_guard_and_fail_open(self):
        self.assertFalse(blocks("Great question!", stop_hook_active=True))
        self.assertEqual(run_hook(b"not json"), "")
        self.assertEqual(run_hook({"last_assistant_message": ""}), "")

    def test_utf8_bytes(self):
        raw = '{"last_assistant_message": "Build failed ❌ on step 2."}'.encode("utf-8")
        self.assertTrue(run_hook(raw))


@unittest.skipUnless(BASH, "bash (Git Bash on Windows) not available")
class SessionStartTests(unittest.TestCase):
    def test_core_payload(self):
        out = subprocess.run([BASH, str(ROOT / "hooks" / "session_start.sh"), "core"],
                             capture_output=True, check=True)
        payload = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "SessionStart")
        self.assertTrue(payload["additionalContext"].startswith("# Synapse rules"))

    def test_unknown_argument_prints_nothing(self):
        out = subprocess.run([BASH, str(ROOT / "hooks" / "session_start.sh"), "nope"],
                             capture_output=True, check=True)
        self.assertEqual(out.stdout, b"")


class ContextBuildTests(unittest.TestCase):
    def test_payloads_current_and_under_cap(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "build_context.py"), "--check"],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


if __name__ == "__main__":
    unittest.main()
