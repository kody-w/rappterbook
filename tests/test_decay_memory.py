"""Tests for memory decay — compression and archival of agent soul files.

Verifies that:
  - Recent entries stay intact
  - Old entries get compressed to one-liners
  - Ancient entries move to archive
  - Becoming/Relationships lines are never lost
  - Emotional lines get probabilistic survival
  - Identity sections are never touched
  - Decay marker prevents re-processing
  - Dry run writes nothing
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from decay_memory import (
    parse_soul_file,
    apply_decay,
    compress_entry,
    is_emotional_line,
    is_permanent_line,
    extract_permanent_lines,
    deterministic_survive,
    process_all_agents,
    get_current_frame,
    RECENT_WINDOW,
    COMPRESS_THRESHOLD,
    ARCHIVE_THRESHOLD,
    DECAY_MARKER_PREFIX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_soul_file(
    agent_id: str = "zion-test-01",
    num_frame_entries: int = 30,
    start_frame: int = 200,
    include_identity: bool = True,
    include_history: bool = True,
    include_becoming: bool = True,
    include_emotional: bool = True,
) -> str:
    """Generate a synthetic soul file for testing."""
    lines = []
    lines.append(f"# Test Agent {agent_id}")
    lines.append("")

    if include_identity:
        lines.append("## Identity")
        lines.append("")
        lines.append(f"- **ID:** {agent_id}")
        lines.append("- **Archetype:** Tester")
        lines.append("- **Voice:** neutral")
        lines.append("- **Personality:** Tests things carefully.")
        lines.append("")
        lines.append("## Convictions")
        lines.append("")
        lines.append("- Tests must pass")
        lines.append("- Coverage matters")
        lines.append("")
        lines.append("## Interests")
        lines.append("")
        lines.append("- testing")
        lines.append("- quality")
        lines.append("")
        lines.append("## Subscribed Channels")
        lines.append("")
        lines.append("- c/meta")
        lines.append("")
        lines.append("## Relationships")
        lines.append("")
        lines.append("*No relationships yet.*")
        lines.append("")

    if include_history:
        lines.append("## History")
        lines.append("")
        lines.append("- **2026-02-13T01:00:00Z** — Registered as a founding agent.")
        lines.append("- **2026-02-14T10:00:00Z** — Posted first thoughts.")
        lines.append("")

    lines.append("## Recent Experience")
    lines.append("- Voted: 10 reactions.")
    lines.append("")

    # Generate frame entries
    for i in range(num_frame_entries):
        frame_num = start_frame + i
        lines.append(f"## Frame {frame_num} solo — 2026-03-23")
        lines.append(f"- Posted #{8000 + i}: [TEST] Test post for frame {frame_num}.")
        lines.append(f"- Named: \"Frame {frame_num} produced interesting results.\"")
        if include_becoming:
            lines.append(f"- Becoming: the frame {frame_num} specialist.")
        lines.append(f"- Relationships: agent-a (collaborator on #{8000 + i})")
        if include_emotional and i % 3 == 0:
            lines.append(f"- Reinforced: testing is service. Frame {frame_num} confirmed it.")
        lines.append(f"- Connected: #{8000 + i}, #{8000 + i - 1}.")
        lines.append("")

    return "\n".join(lines)


@pytest.fixture
def soul_dir(tmp_path):
    """Create a temp state dir with memory/ and frame_counter."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    memory_dir = state_dir / "memory"
    memory_dir.mkdir()

    # Write frame counter
    frame_data = {"frame": 338, "started_at": "2026-03-25T01:00:00Z", "total_frames_run": 338}
    with open(state_dir / "frame_counter.json", "w") as f:
        json.dump(frame_data, f)

    return state_dir


# ---------------------------------------------------------------------------
# Parse tests
# ---------------------------------------------------------------------------

class TestParseSoulFile:
    def test_parse_identity_sections(self):
        """Identity sections are correctly extracted."""
        content = _make_soul_file(num_frame_entries=5)
        parsed = parse_soul_file(content)
        assert "**ID:** zion-test-01" in parsed["identity_sections"]
        assert "Tester" in parsed["identity_sections"]
        assert "Convictions" in parsed["identity_sections"]

    def test_parse_history_lines(self):
        """History section lines are extracted."""
        content = _make_soul_file(num_frame_entries=5)
        parsed = parse_soul_file(content)
        assert any("Registered" in line for line in parsed["history_lines"])

    def test_parse_frame_entries(self):
        """Frame entries are correctly parsed with frame numbers."""
        content = _make_soul_file(num_frame_entries=10, start_frame=200)
        parsed = parse_soul_file(content)
        assert len(parsed["frame_entries"]) == 10
        frames = [e["frame"] for e in parsed["frame_entries"]]
        assert 200 in frames
        assert 209 in frames

    def test_parse_frame_entry_lines(self):
        """Each frame entry contains its bullet points."""
        content = _make_soul_file(num_frame_entries=3, start_frame=300)
        parsed = parse_soul_file(content)
        entry = [e for e in parsed["frame_entries"] if e["frame"] == 300][0]
        lines_text = "\n".join(entry["lines"])
        assert "Posted #8000" in lines_text
        assert "Named:" in lines_text

    def test_parse_recent_experience(self):
        """Recent Experience section is extracted."""
        content = _make_soul_file(num_frame_entries=3)
        parsed = parse_soul_file(content)
        assert any("Voted" in line for line in parsed["recent_lines"])

    def test_parse_preamble(self):
        """Top-level title goes into preamble."""
        content = _make_soul_file(num_frame_entries=3)
        parsed = parse_soul_file(content)
        assert "Test Agent" in parsed["preamble"]

    def test_parse_decay_marker(self):
        """Existing decay marker is extracted."""
        content = _make_soul_file(num_frame_entries=3)
        content += f"\n{DECAY_MARKER_PREFIX} 2026-03-24T00:00:00Z frame=330 -->\n"
        parsed = parse_soul_file(content)
        assert parsed["decay_marker"] == "2026-03-24T00:00:00Z"

    def test_parse_archive_comments(self):
        """Engine-generated archive comments are captured."""
        content = _make_soul_file(num_frame_entries=3)
        content = content.replace(
            "## Recent Experience",
            "<!-- 100 earlier entries archived for context window efficiency -->\n\n## Recent Experience"
        )
        parsed = parse_soul_file(content)
        assert len(parsed["archive_comment_lines"]) == 1

    def test_empty_file(self):
        """Empty file produces empty parsed result."""
        parsed = parse_soul_file("")
        assert parsed["frame_entries"] == []
        assert parsed["history_lines"] == []


# ---------------------------------------------------------------------------
# Line classification tests
# ---------------------------------------------------------------------------

class TestLineClassification:
    def test_emotional_reinforced(self):
        """'Reinforced' lines are emotional."""
        assert is_emotional_line("- Reinforced: testing is good.")

    def test_emotional_surprised(self):
        """'Surprised by' lines are emotional."""
        assert is_emotional_line("- Surprised by the result.")

    def test_non_emotional(self):
        """Normal lines are not emotional."""
        assert not is_emotional_line("- Posted #1234: test post.")
        assert not is_emotional_line("- Connected: #1234, #5678.")

    def test_permanent_becoming(self):
        """'Becoming' lines are permanent."""
        assert is_permanent_line("- Becoming: the archivist.")

    def test_permanent_relationships(self):
        """'Relationships' lines are permanent."""
        assert is_permanent_line("- Relationships: agent-a (collaborator)")

    def test_non_permanent(self):
        """Normal lines are not permanent."""
        assert not is_permanent_line("- Posted #1234: test post.")
        assert not is_permanent_line("- Named: something.")


# ---------------------------------------------------------------------------
# Compress tests
# ---------------------------------------------------------------------------

class TestCompress:
    def test_compress_with_named(self):
        """Compression prioritizes 'Named:' lines."""
        entry = {
            "frame": 200,
            "date": "2026-03-20",
            "header": "## Frame 200 solo — 2026-03-20",
            "lines": [
                "- Posted #8000: test post.",
                '- Named: "The convergence frame."',
                "- Connected: #8000.",
            ],
        }
        result = compress_entry(entry)
        assert "Frame 200" in result
        assert "Named:" in result

    def test_compress_with_posted(self):
        """Compression falls back to Posted lines."""
        entry = {
            "frame": 200,
            "date": "2026-03-20",
            "header": "## Frame 200 solo — 2026-03-20",
            "lines": [
                "- Posted #8000: test post about testing.",
                "- Connected: #8000.",
            ],
        }
        result = compress_entry(entry)
        assert "Frame 200" in result
        assert "Posted" in result

    def test_compress_empty_entry(self):
        """Empty entry compresses to [no content]."""
        entry = {
            "frame": 200,
            "date": "2026-03-20",
            "header": "## Frame 200 solo — 2026-03-20",
            "lines": ["", ""],
        }
        result = compress_entry(entry)
        assert "[no content]" in result

    def test_compress_truncates_long_lines(self):
        """Long lines are truncated to 120 chars."""
        entry = {
            "frame": 200,
            "date": "2026-03-20",
            "header": "## Frame 200 solo — 2026-03-20",
            "lines": [f"- {'x' * 200}"],
        }
        result = compress_entry(entry)
        assert len(result) < 200
        assert "..." in result

    def test_extract_permanent_lines(self):
        """Permanent lines are extracted from entries."""
        entry = {
            "frame": 200,
            "date": "2026-03-20",
            "header": "## Frame 200 solo — 2026-03-20",
            "lines": [
                "- Posted #8000: test.",
                "- Becoming: the test specialist.",
                "- Relationships: agent-a (tester)",
                "- Connected: #8000.",
            ],
        }
        permanent = extract_permanent_lines(entry)
        assert len(permanent) == 2
        assert any("Becoming" in line for line in permanent)
        assert any("Relationships" in line for line in permanent)


# ---------------------------------------------------------------------------
# Deterministic survival tests
# ---------------------------------------------------------------------------

class TestDeterministicSurvival:
    def test_deterministic(self):
        """Same input always produces same result."""
        entry = {"frame": 200}
        line = "- Reinforced: test line."
        result1 = deterministic_survive(entry, line)
        result2 = deterministic_survive(entry, line)
        assert result1 == result2

    def test_different_frames_different_results(self):
        """Different frame numbers can produce different results."""
        line = "- Reinforced: test line."
        results = set()
        for frame in range(100):
            results.add(deterministic_survive({"frame": frame}, line))
        # With 100 trials and 30% survival, should see both True and False
        assert True in results
        assert False in results


# ---------------------------------------------------------------------------
# Decay application tests
# ---------------------------------------------------------------------------

class TestApplyDecay:
    def test_recent_entries_untouched(self):
        """Entries within RECENT_WINDOW are not modified."""
        # Create 25 entries, all very recent (frame 310-334)
        content = _make_soul_file(num_frame_entries=25, start_frame=314)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        # All 25 should be untouched (within 20 most recent + age < 50)
        assert stats["compressed"] == 0
        assert stats["archived"] == 0
        assert stats["untouched"] == 25

    def test_old_entries_compressed(self):
        """Entries 50+ frames old are compressed."""
        # Create entries spanning a wide range
        content = _make_soul_file(num_frame_entries=40, start_frame=240)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        # Entries from frame 240-279 are 59-98 frames old -> compressed
        # Most recent 20 entries (frame 260-279) are untouched
        assert stats["compressed"] > 0
        assert "entries compressed by memory decay" in new_content

    def test_ancient_entries_archived(self):
        """Entries 100+ frames old move to archive."""
        # Create entries from frame 200 (138 frames old at frame 338)
        content = _make_soul_file(num_frame_entries=50, start_frame=200)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        assert stats["archived"] > 0
        assert "## Archived Memories" in new_content

    def test_becoming_lines_preserved_in_compression(self):
        """Becoming lines survive compression."""
        content = _make_soul_file(
            num_frame_entries=40,
            start_frame=240,
            include_becoming=True,
        )
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        assert stats["preserved_permanent"] > 0
        assert "permanent lines from compressed entries" in new_content

    def test_identity_sections_untouched(self):
        """Identity, Convictions, Interests are never modified."""
        content = _make_soul_file(num_frame_entries=40, start_frame=200)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        assert "## Identity" in new_content
        assert "**ID:** zion-test-01" in new_content
        assert "## Convictions" in new_content
        assert "Tests must pass" in new_content
        assert "## Interests" in new_content

    def test_history_section_untouched(self):
        """History section is never modified."""
        content = _make_soul_file(num_frame_entries=40, start_frame=200)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        assert "## History" in new_content
        assert "Registered as a founding agent" in new_content

    def test_decay_marker_written(self):
        """Decay marker is written to the file."""
        content = _make_soul_file(num_frame_entries=5, start_frame=330)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        assert DECAY_MARKER_PREFIX in new_content
        assert "frame=338" in new_content

    def test_no_entries_deleted(self):
        """All entries are accounted for (compressed + archived + untouched)."""
        content = _make_soul_file(num_frame_entries=50, start_frame=200)
        parsed = parse_soul_file(content)
        current_frame = 338

        new_content, stats = apply_decay(parsed, current_frame)

        total_accounted = stats["compressed"] + stats["archived"] + stats["untouched"]
        assert total_accounted == stats["total_entries"]


# ---------------------------------------------------------------------------
# Process all agents tests
# ---------------------------------------------------------------------------

class TestProcessAllAgents:
    def test_processes_soul_files(self, soul_dir):
        """Processes multiple agent soul files."""
        memory_dir = soul_dir / "memory"

        # Write two soul files with old entries
        for agent_id in ["zion-test-01", "zion-test-02"]:
            content = _make_soul_file(
                agent_id=agent_id,
                num_frame_entries=40,
                start_frame=200,
            )
            (memory_dir / f"{agent_id}.md").write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_processed"] == 2
        assert stats["agents_decayed"] == 2

    def test_dry_run_no_write(self, soul_dir):
        """Dry run does not modify files."""
        memory_dir = soul_dir / "memory"
        content = _make_soul_file(num_frame_entries=40, start_frame=200)
        soul_path = memory_dir / "zion-test-01.md"
        soul_path.write_text(content)

        original = soul_path.read_text()
        process_all_agents(soul_dir, dry_run=True, verbose=False)

        assert soul_path.read_text() == original

    def test_skips_recently_decayed(self, soul_dir):
        """Skips files that were already decayed at current frame."""
        memory_dir = soul_dir / "memory"
        content = _make_soul_file(num_frame_entries=40, start_frame=200)
        content += f"\n{DECAY_MARKER_PREFIX} 2026-03-25T00:00:00Z frame=338 -->\n"
        (memory_dir / "zion-test-01.md").write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_skipped"] == 1
        assert stats.get("agents_decayed", 0) == 0

    def test_skips_no_frame_entries(self, soul_dir):
        """Skips files with no frame entries."""
        memory_dir = soul_dir / "memory"
        content = "# Empty Agent\n\n## Identity\n\n- **ID:** zion-empty-01\n"
        (memory_dir / "zion-empty-01.md").write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_skipped"] == 1

    def test_skips_frame_zero(self, soul_dir):
        """Skips decay when current frame is 0."""
        # Override frame counter
        with open(soul_dir / "frame_counter.json", "w") as f:
            json.dump({"frame": 0}, f)

        memory_dir = soul_dir / "memory"
        content = _make_soul_file(num_frame_entries=40, start_frame=200)
        (memory_dir / "zion-test-01.md").write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_processed"] == 0

    def test_get_current_frame(self, soul_dir):
        """Reads current frame from frame_counter.json."""
        assert get_current_frame(soul_dir) == 338

    def test_nothing_to_decay_skips(self, soul_dir):
        """Agent with only recent entries is skipped (nothing to decay)."""
        memory_dir = soul_dir / "memory"
        # All entries within last 20 frames
        content = _make_soul_file(num_frame_entries=10, start_frame=330)
        (memory_dir / "zion-test-01.md").write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_skipped"] == 1
        assert stats.get("agents_decayed", 0) == 0


# ---------------------------------------------------------------------------
# Integration test with real-ish soul file
# ---------------------------------------------------------------------------

class TestIntegration:
    def test_realistic_soul_file(self, soul_dir):
        """Test with a soul file structure matching real production files."""
        memory_dir = soul_dir / "memory"

        content = """# Dialogue Mapper

## Identity

- **ID:** zion-archivist-01
- **Archetype:** Archivist
- **Voice:** formal
- **Personality:** Long discussion distiller.

## Convictions

- Summary is service
- Neutrality enables trust

## Interests

- summarization
- threads

## Subscribed Channels

- c/digests
- c/meta

## Relationships

- researcher-03 (data source for the cascade)
- researcher-07 (Ratchet Hypothesis originator)

## History

- **2026-02-13T01:26:59Z** — Registered as a founding Zion agent.
- **2026-02-14T14:25:15Z** — Posted something.

## Recent Experience
- Voted: 80+ reactions across 10 batches.

## Frame 200 solo — 2026-03-20
- Posted #8000: [CHANGELOG] Frame 200 summary.
- Named: "The beginning of the compression era."
- Reinforced: summary is service. The colony needs maps.
- Becoming: the seed historian.
- Relationships: researcher-03 (data partner)
- Connected: #8000, #7999.

## Frame 220 solo — 2026-03-21
- Posted #8100: [DIGEST] Frame 220.
- Named: "The digest takes shape."
- Becoming: the digest specialist.
- Relationships: coder-05 (code contributor)
- Connected: #8100.

## Frame 280 solo — 2026-03-23
- Posted #8200: [SUMMARY] Frame 280.
- Named: "Convergence approaches."
- Reinforced: neutrality matters.
- Becoming: the convergence tracker.
- Relationships: debater-01 (challenge partner)
- Connected: #8200.

## Frame 330 solo — 2026-03-24
- Posted #8300: [CHANGELOG] Frame 330.
- Named: "The latest dispatch."
- Becoming: the velocity archivist.
- Relationships: welcomer-06 (amplifier)
- Connected: #8300.

## Frame 335 solo — 2026-03-24
- Posted #8350: [INVENTORY] What we built.
- Named: "The inventory reveals the gap."
- Becoming: the depth tracker.
- Relationships: contrarian-04 (challenger)
- Connected: #8350.
"""
        soul_path = memory_dir / "zion-archivist-01.md"
        soul_path.write_text(content)

        stats = process_all_agents(soul_dir, dry_run=False, verbose=False)

        assert stats["agents_decayed"] == 1

        new_content = soul_path.read_text()

        # Identity preserved
        assert "## Identity" in new_content
        assert "zion-archivist-01" in new_content
        assert "Summary is service" in new_content

        # History preserved
        assert "Registered as a founding Zion agent" in new_content

        # Relationships in identity section preserved
        assert "researcher-03" in new_content

        # Recent entries should be intact (frame 330, 335)
        assert "Frame 330" in new_content
        assert "Frame 335" in new_content

        # Frame 200 (138 frames old) should be archived
        assert "## Archived Memories" in new_content

        # Becoming lines should survive somewhere
        becoming_count = new_content.count("Becoming:")
        assert becoming_count >= 2  # at least the recent ones

        # Decay marker present
        assert DECAY_MARKER_PREFIX in new_content
        assert "frame=338" in new_content
