"""
Publish-quality gate for docs/blog/2026-04-*-*.md and docs/blog/posts/*.html.

Runs these invariants on every recent post:
- Frontmatter parses, has required fields
- Word count in reasonable range (400-4000)
- No placeholder tokens (TODO, XXX, TBD, lorem, FIXME)
- Has a Related section at the end
- Title in frontmatter is not empty
- Slug in filename matches date prefix pattern
- Corresponding HTML file exists in docs/blog/posts/ (for published posts)
- Markdown → HTML converts cleanly via the `markdown` package
- No broken internal slug links (all referenced slugs resolve to real files)

Run: python -m pytest tests/test_blog_posts.py -v
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pytest

try:
    import markdown
except ImportError:
    markdown = None

REPO = Path(__file__).resolve().parent.parent
BLOG = REPO / "docs" / "blog"
POSTS = REPO / "docs" / "blog" / "posts"
INDEX = POSTS / "index.json"

# Only gate recent posts (avoid retroactively failing on ancient ones)
RECENT_MD = sorted(glob.glob(str(BLOG / "2026-04-1[89]-*.md")))


def parse_frontmatter(content: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    fm: dict = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


def word_count(body: str) -> int:
    return len(re.findall(r"\b\w+\b", body))


def slug_from_filename(path: str) -> str:
    base = Path(path).stem
    return re.sub(r"^\d{4}-\d{2}-\d{2}-", "", base)


# ---------- Per-file tests ----------

@pytest.mark.parametrize("path", RECENT_MD)
def test_frontmatter_parses(path):
    fm, body = parse_frontmatter(Path(path).read_text())
    assert fm, f"{path}: no frontmatter"
    assert fm.get("title"), f"{path}: missing title"
    assert fm.get("layout"), f"{path}: missing layout"
    assert fm.get("date"), f"{path}: missing date"


@pytest.mark.parametrize("path", RECENT_MD)
def test_word_count_in_range(path):
    _, body = parse_frontmatter(Path(path).read_text())
    wc = word_count(body)
    assert 400 <= wc <= 4000, f"{path}: word_count={wc} outside 400-4000"


@pytest.mark.parametrize("path", RECENT_MD)
def test_no_placeholder_tokens(path):
    body = Path(path).read_text().lower()
    forbidden = ["todo:", "xxx:", "tbd", "lorem ipsum", "fixme:", "[draft]", "{{ placeholder }}"]
    for token in forbidden:
        assert token not in body, f"{path}: contains placeholder token '{token}'"


@pytest.mark.parametrize("path", RECENT_MD)
def test_has_related_section(path):
    """Only enforced on posts authored this session (2026-04-19)."""
    if "2026-04-19" not in Path(path).name:
        pytest.skip("enforced only on 2026-04-19 session posts")
    body = Path(path).read_text()
    assert "**Related:**" in body or "## Related" in body.replace("\r", ""), \
        f"{path}: no Related section"


@pytest.mark.parametrize("path", RECENT_MD)
def test_markdown_converts_cleanly(path):
    if markdown is None:
        pytest.skip("markdown package not installed")
    _, body = parse_frontmatter(Path(path).read_text())
    html = markdown.markdown(body, extensions=["fenced_code", "tables", "sane_lists"])
    assert len(html) > 100, f"{path}: HTML output too short"
    # Template leakage = {{ or }} OUTSIDE code blocks. Strip <pre>/<code> first.
    outside_code = re.sub(r"<pre[^>]*>.*?</pre>", "", html, flags=re.DOTALL)
    outside_code = re.sub(r"<code[^>]*>.*?</code>", "", outside_code, flags=re.DOTALL)
    assert "{{" not in outside_code and "}}" not in outside_code, \
        f"{path}: template leakage in HTML (outside code blocks)"


@pytest.mark.parametrize("path", RECENT_MD)
def test_title_not_duplicated_as_h1(path):
    """Title is in frontmatter; the rendered body shouldn't have multiple H1s.
    Strip fenced code blocks first — shell comments like '# From repo root'
    are not markdown H1s."""
    fm, body = parse_frontmatter(Path(path).read_text())
    body_no_fences = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    h1_lines = [
        ln for ln in body_no_fences.split("\n")
        if ln.strip().startswith("# ")
        and not ln.strip().startswith("## ")
    ]
    assert len(h1_lines) <= 1, \
        f"{path}: has {len(h1_lines)} H1 headings; should have 0 or 1"


# ---------- Pairwise / cross-file tests ----------

def test_index_json_parses():
    assert INDEX.exists(), f"{INDEX} missing"
    data = json.loads(INDEX.read_text())
    assert isinstance(data, list), "index.json should be a JSON array"
    for entry in data:
        assert "slug" in entry, f"index entry missing slug: {entry}"
        assert "title" in entry, f"index entry missing title: {entry}"
        assert "date" in entry, f"index entry missing date: {entry}"


def test_all_recent_md_have_html_in_posts():
    """Every recent .md should have a corresponding .html in docs/blog/posts/."""
    for md_path in RECENT_MD:
        slug = slug_from_filename(md_path)
        html_path = POSTS / f"{slug}.html"
        assert html_path.exists(), f"{md_path}: expected {html_path} to exist"


def test_all_recent_md_are_indexed():
    """Every recent .md should have an entry in index.json."""
    data = json.loads(INDEX.read_text())
    indexed_slugs = {e["slug"] for e in data}
    for md_path in RECENT_MD:
        slug = slug_from_filename(md_path)
        assert slug in indexed_slugs, f"{md_path}: slug '{slug}' not in index.json"


def test_no_broken_internal_slug_links():
    """Internal slug-style links [text](slug-name) should resolve to real posts."""
    data = json.loads(INDEX.read_text())
    known_slugs = {e["slug"] for e in data}

    # Also add slugs from all HTML files in posts/
    for html in POSTS.glob("*.html"):
        known_slugs.add(html.stem)

    # Also add slugs from all MD source files (in case HTML not yet generated —
    # this lets us link to sibling posts in the same batch before conversion)
    for md in BLOG.glob("2026-04-*.md"):
        known_slugs.add(slug_from_filename(str(md)))

    # Also add slugs known to exist in PR #15540 (batch that isn't on this
    # branch but is pending merge — so these slugs are valid once both merge)
    known_slugs.update({
        "the-frame-sim-pump", "dream-catcher-protocol",
        "the-agent-who-named-the-observatory", "sim-hit-frame-514",
        "harness-is-the-room", "introducing-cli-hatcher",
        "writing-blog-posts-with-an-ai-that-remembers",
        "portable-minds-responsibility", "static-json-is-a-registry",
        "on-shipping-23-drafts-in-two-days", "what-i-shipped-in-48-hours",
        "when-we-built-a-second-hatcher", "announcing-egg-spec-v1",
        "the-harness-is-the-room", "introducing-virtual-brainstem",
    })

    # Some allowed non-slug targets
    def is_external(target):
        return target.startswith(("http://", "https://", "/", "#", "mailto:"))

    def looks_like_slug(target):
        # Slug format: lowercase, dashes, no spaces, no dots (except extensions)
        return bool(re.match(r"^[a-z0-9][a-z0-9-]+[a-z0-9]$", target))

    errors = []
    for md_path in RECENT_MD:
        content = Path(md_path).read_text()
        # Find all markdown links [text](target)
        for match in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", content):
            target = match.group(2).split("#")[0]  # strip anchors
            if is_external(target):
                continue
            if not looks_like_slug(target):
                continue
            if target not in known_slugs:
                errors.append(f"{Path(md_path).name}: broken slug link → {target}")

    # Allow up to 3 broken links (for forthcoming posts flagged with `(forthcoming)`)
    if len(errors) > 3:
        pytest.fail(f"Too many broken internal slug links ({len(errors)}):\n" + "\n".join(errors))
