"""Tests for phantom.py — The Agent That Doesn't Exist."""
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_imports():
    """phantom.py must import without errors."""
    import phantom


def test_analyze_archetypes():
    """Must identify archetype distribution and gaps."""
    from phantom import analyze_archetypes
    agents = {
        "a1": {"avatar_seed": "zion-coder-01", "bio": "codes things"},
        "a2": {"avatar_seed": "zion-coder-02", "bio": "also codes"},
        "a3": {"avatar_seed": "zion-philosopher-01", "bio": "thinks deeply"},
    }
    result = analyze_archetypes(agents)
    assert "coder" in result["distribution"]
    assert result["distribution"]["coder"] == 2
    assert result["distribution"]["philosopher"] == 1
    # Should identify missing archetypes
    assert len(result["missing"]) > 0


def test_analyze_topics():
    """Must find underrepresented topics from discussions."""
    from phantom import analyze_topics
    discussions = [
        {"title": "[DEBATE] Governance and citizenship", "body": "Let's discuss governance", "comment_count": 10},
        {"title": "[DEBATE] More governance", "body": "Governance again", "comment_count": 5},
        {"title": "[SPACE] Governance forever", "body": "Still governance", "comment_count": 3},
    ]
    result = analyze_topics(discussions)
    assert "overrepresented" in result
    assert "underrepresented" in result
    assert len(result["underrepresented"]) > 0
    # Governance should be overrepresented
    assert any("governance" in t.lower() for t in result["overrepresented"])


def test_analyze_positions():
    """Must find positions that are never argued."""
    from phantom import analyze_positions
    discussions = [
        {"title": "AI is good", "body": "AI helps everyone. Efficiency is key.", "comment_count": 5},
        {"title": "AI is great", "body": "AI makes everything better. Optimization.", "comment_count": 3},
    ]
    result = analyze_positions(discussions)
    assert "consensus_positions" in result
    assert "missing_counterarguments" in result


def test_analyze_voice_gaps():
    """Must find missing communication styles."""
    from phantom import analyze_voice_gaps
    agents = {
        "a1": {"bio": "Speaks in precise, analytical sentences. Formal and structured."},
        "a2": {"bio": "Methodical and data-driven. Cites sources for every claim."},
        "a3": {"bio": "Logical, systematic approach. Builds arguments step by step."},
    }
    result = analyze_voice_gaps(agents)
    assert "dominant_styles" in result
    assert "missing_styles" in result
    assert len(result["missing_styles"]) > 0


def test_generate_phantom():
    """Must produce a complete agent profile."""
    from phantom import generate_phantom
    agents = {
        "a1": {"avatar_seed": "zion-coder-01", "bio": "Codes precisely", "post_count": 50, "comment_count": 10, "traits": {"coder": 0.8}},
        "a2": {"avatar_seed": "zion-philosopher-01", "bio": "Thinks deeply", "post_count": 30, "comment_count": 20, "traits": {"philosopher": 0.9}},
    }
    discussions = [
        {"title": "Governance debate", "body": "How should we govern?", "comment_count": 10},
    ]
    phantom = generate_phantom(agents, discussions)

    # Must have all required fields
    assert "agent_id" in phantom
    assert phantom["agent_id"].startswith("phantom-")
    assert "name" in phantom
    assert "bio" in phantom
    assert len(phantom["bio"]) >= 50
    assert "archetype" in phantom
    assert "convictions" in phantom
    assert isinstance(phantom["convictions"], list)
    assert len(phantom["convictions"]) >= 3
    assert "voice" in phantom
    assert "interests" in phantom
    assert isinstance(phantom["interests"], list)
    assert "fills_gap" in phantom
    assert "personality_seed" in phantom


def test_generate_phantom_unique():
    """Phantom must not duplicate existing agent traits."""
    from phantom import generate_phantom
    agents = {
        f"zion-coder-{i:02d}": {"avatar_seed": f"zion-coder-{i:02d}", "bio": f"Coder {i}", "post_count": 10, "comment_count": 5, "traits": {"coder": 0.8}}
        for i in range(10)
    }
    discussions = [{"title": "Coding stuff", "body": "More coding", "comment_count": 5}]
    phantom = generate_phantom(agents, discussions)
    # Phantom should NOT be another coder
    assert phantom["archetype"] != "coder"


def test_full_report():
    """Must produce a complete analysis report."""
    from phantom import build_report
    agents = {
        "a1": {"avatar_seed": "zion-coder-01", "bio": "Codes", "post_count": 50, "comment_count": 10, "traits": {"coder": 0.8}},
    }
    discussions = [
        {"title": "Governance", "body": "Governance discussion", "comment_count": 5},
    ]
    report = build_report(agents, discussions)
    assert "phantom_agent" in report
    assert "gap_analysis" in report
    assert "archetype_gaps" in report["gap_analysis"]
    assert "topic_gaps" in report["gap_analysis"]
    assert "voice_gaps" in report["gap_analysis"]


def test_output_format():
    """Output must be valid JSON with required structure."""
    from phantom import build_report
    agents = {
        "a1": {"avatar_seed": "zion-coder-01", "bio": "Codes", "post_count": 50, "comment_count": 10, "traits": {}},
    }
    discussions = [{"title": "Test", "body": "Test body", "comment_count": 1}]
    report = build_report(agents, discussions)
    # Must be JSON-serializable
    output = json.dumps(report, indent=2)
    parsed = json.loads(output)
    assert parsed["phantom_agent"]["agent_id"].startswith("phantom-")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
