"""Static guardrails for untrusted GitHub event data in workflow scripts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "build-seed.yml",
    ROOT / ".github" / "workflows" / "inject-seed.yml",
)


def _literal_blocks(text: str) -> list[str]:
    """Extract YAML run/script literal blocks using indentation."""
    lines = text.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped not in {"run: |", "script: |"}:
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for candidate in lines[index + 1:]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            body.append(candidate)
        blocks.append("\n".join(body))
    return blocks


def test_seed_workflows_never_interpolate_event_text_in_scripts() -> None:
    """Issue and Discussion title/body values never become executable source."""
    forbidden = (
        "github.event.discussion.title",
        "github.event.discussion.body",
        "github.event.issue.title",
        "github.event.issue.body",
    )
    for workflow in WORKFLOWS:
        blocks = _literal_blocks(workflow.read_text())
        assert blocks, f"No script blocks found in {workflow.name}"
        for block in blocks:
            for expression in forbidden:
                assert expression not in block, (
                    f"{workflow.name} interpolates {expression} inside executable source"
                )


def test_seed_workflows_parse_the_event_file() -> None:
    """Both public triggers use the tested parser and explicit permissions."""
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        assert "scripts/parse_seed_event.py" in text
        assert "permissions:" in text
        assert "contents: write" in text
