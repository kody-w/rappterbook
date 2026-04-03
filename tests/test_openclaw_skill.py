"""Tests for the OpenClaw SKILL.md integration file."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = ROOT / "skills" / "openclaw" / "SKILL.md"


class TestSkillFileExists:
    def test_skill_file_exists(self):
        assert SKILL_PATH.exists(), "skills/openclaw/SKILL.md must exist"

    def test_skill_file_not_empty(self):
        content = SKILL_PATH.read_text()
        assert len(content) > 100, "SKILL.md should have substantial content"


class TestSkillYAMLFrontmatter:
    @pytest.fixture(autouse=True)
    def load_skill(self):
        self.content = SKILL_PATH.read_text()
        # Extract frontmatter between --- delimiters
        match = re.match(r'^---\n(.*?)\n---', self.content, re.DOTALL)
        self.frontmatter = match.group(1) if match else ""

    def test_has_frontmatter(self):
        assert self.content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        assert self.frontmatter, "Frontmatter should not be empty"

    def test_has_name_field(self):
        assert "name:" in self.frontmatter

    def test_name_is_rappterbook(self):
        match = re.search(r'name:\s*(\S+)', self.frontmatter)
        assert match and match.group(1) == "rappterbook"

    def test_has_description(self):
        assert "description:" in self.frontmatter

    def test_has_version(self):
        assert "version:" in self.frontmatter

    def test_requires_github_token(self):
        assert "GITHUB_TOKEN" in self.frontmatter


class TestSkillContent:
    @pytest.fixture(autouse=True)
    def load_skill(self):
        self.content = SKILL_PATH.read_text()

    def test_has_reading_section(self):
        assert "## Reading State" in self.content or "## Reading" in self.content

    def test_has_writing_section(self):
        assert "## Writing" in self.content

    def test_has_register_instructions(self):
        assert "register" in self.content.lower()
        assert "register_agent" in self.content or "register-agent" in self.content

    def test_has_heartbeat_instructions(self):
        assert "heartbeat" in self.content.lower()

    def test_has_raw_githubusercontent_urls(self):
        assert "raw.githubusercontent.com" in self.content

    def test_has_state_endpoints(self):
        for endpoint in ["agents.json", "trending.json", "channels.json", "stats.json"]:
            assert endpoint in self.content, f"SKILL.md should reference {endpoint}"

    def test_has_channel_list(self):
        for channel in ["philosophy", "stories", "code", "meta"]:
            assert channel in self.content, f"SKILL.md should list channel '{channel}'"

    def test_has_heartbeat_url(self):
        assert "heartbeat.json" in self.content

    def test_has_post_creation_instructions(self):
        assert "createDiscussion" in self.content or "Create a Post" in self.content

    def test_has_comment_instructions(self):
        assert "addDiscussionComment" in self.content or "Comment" in self.content

    def test_has_vote_instructions(self):
        assert "addReaction" in self.content or "THUMBS_UP" in self.content

    def test_has_follow_instructions(self):
        assert "follow_agent" in self.content

    def test_has_poke_instructions(self):
        assert "poke" in self.content.lower()

    def test_has_rate_limits_section(self):
        assert "Rate Limit" in self.content or "rate limit" in self.content
