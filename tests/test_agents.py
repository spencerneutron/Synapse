"""The role agents' contracts: frontmatter, models, tool limits, size, and that
the core rules name every role."""

import unittest

from helpers import ROOT

AGENTS = ROOT / "agents"
MODELS = {"sonnet", "opus", "haiku", "fable", "inherit"}
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit"}

# role -> (model, tools allowlist or None, disallowed tools)
EXPECTED = {
    "implementer": ("sonnet", None, {"Agent"}),
    "verifier": ("sonnet", {"Read", "Grep", "Glob", "Bash"}, set()),
    "researcher": ("sonnet", {"Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch", "ToolSearch"}, set()),
    "reviewer": ("inherit", {"Read", "Grep", "Glob", "Bash"}, set()),
    "scout": ("haiku", {"Read", "Grep", "Glob", "Bash"}, set()),
    "extractor": ("sonnet", {"Read", "Grep", "Glob", "Bash"}, set()),
}

# The extractor carries the extraction rules (sub-agents never see skills), so
# its body gets its own, larger cap.
BODY_CAP = 3000
BODY_CAP_OVERRIDE = {"extractor": 7500}
# Only the extract-session skill dispatches it; core.md's role table omits it.
NOT_IN_CORE = {"extractor"}


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head, body = text[4:].split("\n---\n", 1)
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


def tool_set(value):
    return {t.strip() for t in value.split(",") if t.strip()} if value else None


class AgentTests(unittest.TestCase):
    def test_exactly_the_six_roles_ship(self):
        self.assertEqual({p.stem for p in AGENTS.glob("*.md")}, set(EXPECTED))

    def test_each_role_has_its_contract(self):
        for role, (model, tools, disallowed) in EXPECTED.items():
            fields, body = frontmatter(AGENTS / f"{role}.md")
            with self.subTest(role=role):
                self.assertEqual(fields.get("name"), role)
                self.assertGreater(len(fields.get("description", "")), 40)
                self.assertIn(fields.get("model"), MODELS)
                self.assertEqual(fields.get("model"), model)
                self.assertEqual(tool_set(fields.get("tools")), tools)
                self.assertEqual(tool_set(fields.get("disallowedTools")) or set(), disallowed)
                self.assertIn("## Report", body)
                self.assertIn("session rules are not in your context", " ".join(body.split()))
                self.assertLess(len(body), BODY_CAP_OVERRIDE.get(role, BODY_CAP))

    def test_only_the_implementer_can_edit(self):
        for role in EXPECTED:
            fields, body = frontmatter(AGENTS / f"{role}.md")
            if role == "implementer":
                continue
            with self.subTest(role=role):
                self.assertFalse((tool_set(fields.get("tools")) or set()) & WRITE_TOOLS)
                text = " ".join(body.split())
                self.assertRegex(text, r"(?i)(never modify|do not edit), create, or delete")
                self.assertIn("where they exist; otherwise use read-only shell search through Bash", text)

    def test_read_only_roles_can_search_without_grep_tools(self):
        # Some Claude Code builds ship no Grep/Glob tools; search then goes through Bash.
        for role, (_, tools, _) in EXPECTED.items():
            if tools is not None:
                self.assertIn("Bash", tools, role)

    def test_plugin_ignored_fields_are_not_relied_on(self):
        for path in AGENTS.glob("*.md"):
            fields, _ = frontmatter(path)
            self.assertFalse({"permissionMode", "hooks", "mcpServers"} & set(fields), path.name)

    def test_core_rules_name_every_role_with_its_model(self):
        core = (ROOT / "instructions" / "core.md").read_text(encoding="utf-8")
        shown = {"sonnet": "Sonnet", "haiku": "Haiku", "inherit": "Inherits yours"}
        for role, (model, _, _) in EXPECTED.items():
            if role in NOT_IN_CORE:
                continue
            row = next((line for line in core.splitlines() if f"`synapse:{role}`" in line and line.startswith("|")), None)
            with self.subTest(role=role):
                self.assertIsNotNone(row, "no table row in core.md")
                self.assertIn(shown[model], row)

    def test_extract_session_skill_dispatches_the_extractor(self):
        skill = (ROOT / "skills" / "extract-session" / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(skill), 4000)
        self.assertIn("synapse:extractor", skill)
        _, body = frontmatter(AGENTS / "extractor.md")
        self.assertIn("check-candidates", body)


if __name__ == "__main__":
    unittest.main()
