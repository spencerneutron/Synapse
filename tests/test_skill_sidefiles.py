import re
import unittest

from helpers import ROOT

SKILLS = ROOT / "skills"


class SideFileTests(unittest.TestCase):
    def test_quoted_sections_exist(self):
        for skill in ("plan-session", "end-session"):
            text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
            headings = set(re.findall(r"^## (.+?)\s*$",
                                      (SKILLS / skill / "branches.md").read_text(encoding="utf-8"),
                                      re.M))
            names = set()
            for m in re.finditer(r"branches\.md`?(?:\s*\(next to this file\))?\s+section\s+\"([^\"]+)\"",
                                 re.sub(r"\s+", " ", text)):
                names.add(m.group(1))
            self.assertTrue(names, skill)
            for name in names:
                self.assertIn(name, headings, f"{skill}: section {name!r}")

    def test_no_plugin_root_in_side_files(self):
        for f in SKILLS.glob("*/branches.md"):
            self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", f.read_text(encoding="utf-8"), str(f))


if __name__ == "__main__":
    unittest.main()
