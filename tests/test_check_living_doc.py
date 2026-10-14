"""Tests for the living-document QA gate and the two reader intake forms.

No test touches the network: every check runs --offline or with a mocked
fetcher, and http_status is exercised against a mocked opener (cld._open)
and a mocked resolver (cld._resolve).
"""
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_living_doc as cld  # noqa: E402

TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
WORKFLOW_DIR = ROOT / ".github" / "workflows"
README = ROOT / "docs" / "living" / "README.md"
TODAY = dt.date(2026, 10, 10)
SOURCE = "https://example.org/source"


def make_doc(
    body="Plain prose with no claims.\n",
    title="Example topic",
    owner="zion-researcher-01",
    refresh="30",
    verified="2026-10-01",
    sources=(SOURCE,),
    drop=(),
):
    """Build a living document; drop removes front matter keys."""
    lines = ["---"]
    fields = [
        ("title", title),
        ("owner_agent", owner),
        ("refresh_days", refresh),
        ("last_verified", verified),
    ]
    for key, value in fields:
        if key not in drop:
            lines.append(f"{key}: {value}")
    if "sources" not in drop:
        lines.append("sources:")
        lines.extend(f"  - {source}" for source in sources)
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    """Every host 'resolves' to a public address unless a test says otherwise."""
    monkeypatch.setattr(cld, "_resolve", lambda host, port: ["93.184.216.34"])


def write(tmp_path, text, name="doc.md"):
    path = tmp_path / name
    path.write_text(text)
    return path


def rules(report):
    return [error["rule"] for error in report["errors"]]


def check(tmp_path, text, fetcher=None, today=TODAY):
    return cld.check_file(write(tmp_path, text), today=today, fetcher=fetcher)


def ok_fetcher(calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return 200
    return fetch


# --------------------------------------------------------------------------
# Rule 1: front matter
# --------------------------------------------------------------------------

class TestFrontMatter:
    def test_complete_doc_passes(self, tmp_path):
        report = check(tmp_path, make_doc())
        assert report["ok"], report

    @pytest.mark.parametrize("key", cld.REQUIRED_KEYS)
    def test_each_required_key_is_enforced(self, tmp_path, key):
        report = check(tmp_path, make_doc(drop=(key,)))
        assert not report["ok"]
        assert any(key in e["message"] and e["rule"] == "front_matter" for e in report["errors"])

    def test_missing_block(self, tmp_path):
        report = check(tmp_path, "# No front matter\n")
        assert rules(report) == ["front_matter"]

    def test_unclosed_block(self, tmp_path):
        report = check(tmp_path, "---\ntitle: x\n")
        assert rules(report) == ["front_matter"]

    @pytest.mark.parametrize("refresh", ["0", "-3", "thirty", "1.5"])
    def test_refresh_days_must_be_positive_integer(self, tmp_path, refresh):
        report = check(tmp_path, make_doc(refresh=refresh))
        assert "front_matter" in rules(report)

    @pytest.mark.parametrize("verified", ["2026/10/01", "2026-13-01", "yesterday"])
    def test_last_verified_must_be_a_date(self, tmp_path, verified):
        report = check(tmp_path, make_doc(verified=verified))
        assert "front_matter" in rules(report)

    def test_sources_must_be_http_urls(self, tmp_path):
        report = check(tmp_path, make_doc(sources=("ftp://example.org/x",)))
        assert "front_matter" in rules(report)

    def test_sources_must_be_non_empty(self, tmp_path):
        report = check(tmp_path, make_doc(sources=()))
        assert "front_matter" in rules(report)

    def test_flow_list_and_quotes_are_accepted(self, tmp_path):
        text = (
            '---\ntitle: "Quoted: title"\nowner_agent: a\nrefresh_days: 7\n'
            f"last_verified: 2026-10-05\nsources: [{SOURCE}, https://example.org/b]\n---\nBody.\n"
        )
        meta, _, _, errors = cld.split_front_matter(text)
        assert errors == []
        assert meta["title"] == "Quoted: title"
        assert meta["sources"] == [SOURCE, "https://example.org/b"]
        assert check(tmp_path, text)["ok"]

    def test_duplicate_key_is_reported(self, tmp_path):
        text = make_doc().replace("title: Example topic", "title: a\ntitle: b")
        assert "front_matter" in rules(check(tmp_path, text))

    @pytest.mark.parametrize("refresh", ["²", "١٢", "9" * 4301, "123456"])
    def test_non_ascii_or_huge_refresh_days_is_reported_not_a_crash(self, tmp_path, refresh):
        report = check(tmp_path, make_doc(refresh=refresh))
        assert "front_matter" in rules(report)
        assert "internal" not in rules(report)

    @pytest.mark.parametrize("key", ["title", "owner_agent"])
    def test_blank_quoted_values_count_as_missing(self, tmp_path, key):
        text = make_doc().replace(f"{key}: ", f'{key}: " "  # ', 1)
        report = check(tmp_path, text)
        assert any(key in e["message"] for e in report["errors"]), report

    def test_quoted_values_with_trailing_comments(self, tmp_path):
        text = (
            '---\ntitle: "Q" # the title\nowner_agent: \'a\' # owner\nrefresh_days: 7 # weekly\n'
            'last_verified: 2026-10-05\nsources:\n  - "https://example.org/source" # main\n'
            '  - https://example.org/page#frag\n---\nBody.\n'
        )
        meta, _, _, errors = cld.split_front_matter(text)
        assert errors == []
        assert (meta["title"], meta["owner_agent"], meta["refresh_days"]) == ("Q", "a", "7")
        assert meta["sources"] == [SOURCE, "https://example.org/page#frag"]
        assert check(tmp_path, text)["ok"]

    def test_flow_list_keeps_quoted_commas(self, tmp_path):
        text = make_doc().replace(f"sources:\n  - {SOURCE}",
                                  'sources: ["https://example.org/a,b", \'https://example.org/c\']')
        meta, _, _, _ = cld.split_front_matter(text)
        assert meta["sources"] == ["https://example.org/a,b", "https://example.org/c"]
        assert check(tmp_path, text)["ok"]

    def test_non_http_source_is_reported_once(self, tmp_path):
        report = check(tmp_path, make_doc(sources=("not-a-url",)))
        assert rules(report) == ["front_matter"]

    def test_utf8_bom_is_ignored(self, tmp_path):
        path = tmp_path / "bom.md"
        path.write_bytes(b"\xef\xbb\xbf" + make_doc(body="Plain prose.\n").encode())
        assert cld.check_file(path, today=TODAY)["ok"]
        assert cld.split_front_matter("\ufeff" + make_doc())[3] == []


# --------------------------------------------------------------------------
# Rule 3: freshness
# --------------------------------------------------------------------------

class TestFreshness:
    def test_exactly_refresh_days_old_passes(self, tmp_path):
        text = make_doc(refresh="9", verified="2026-10-01")
        assert check(tmp_path, text)["ok"]

    def test_one_day_past_refresh_fails(self, tmp_path):
        text = make_doc(refresh="8", verified="2026-10-01")
        report = check(tmp_path, text)
        assert rules(report) == ["freshness"]
        assert "9 days old" in report["errors"][0]["message"]

    def test_future_date_fails(self, tmp_path):
        report = check(tmp_path, make_doc(verified="2026-10-11"))
        assert rules(report) == ["freshness"]


# --------------------------------------------------------------------------
# Rule 2: links
# --------------------------------------------------------------------------

class TestLinks:
    def test_offline_never_fetches(self, tmp_path):
        body = "See [a page](https://example.org/a).\n"
        report = check(tmp_path, make_doc(body=body), fetcher=None)
        assert report["ok"]
        assert report["network_checked"] is False
        assert report["checked_urls"] == []

    def test_sources_and_body_links_are_fetched_once_each(self, tmp_path):
        calls = []
        body = (
            "See [a](https://example.org/a) and <https://example.org/b>.\n\n"
            f"Again [a](https://example.org/a) and [src]({SOURCE}).\n\n"
            "[ref]: https://example.org/c\n"
        )
        report = check(tmp_path, make_doc(body=body), fetcher=ok_fetcher(calls))
        assert report["ok"], report
        assert sorted(calls) == sorted([
            SOURCE, "https://example.org/a", "https://example.org/b", "https://example.org/c",
        ])

    def test_http_error_status_fails(self, tmp_path):
        body = "See [a](https://example.org/missing).\n"
        fetch = lambda url: 404 if url.endswith("missing") else 200  # noqa: E731
        report = check(tmp_path, make_doc(body=body), fetcher=fetch)
        assert rules(report) == ["links"]
        assert "HTTP 404" in report["errors"][0]["message"]
        assert report["errors"][0]["line"] == 10

    def test_broken_source_fails(self, tmp_path):
        fetch = lambda url: 500  # noqa: E731
        report = check(tmp_path, make_doc(), fetcher=fetch)
        assert rules(report) == ["links"]

    def test_unreachable_url_fails(self, tmp_path):
        def fetch(url):
            raise urllib.error.URLError("dns")
        report = check(tmp_path, make_doc(), fetcher=fetch)
        assert rules(report) == ["links"]
        assert "unreachable" in report["errors"][0]["message"]

    def test_relative_links_checked_even_offline(self, tmp_path):
        (tmp_path / "other.md").write_text("x")
        body = "See [ok](other.md#part), [anchor](#top) and [gone](missing.md).\n"
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["links"]
        assert "missing.md" in report["errors"][0]["message"]

    def test_unsupported_scheme_fails(self, tmp_path):
        body = "Click [me](javascript:alert(1)) or [mail](mailto:a@example.org).\n"
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["links", "links"]

    def test_links_in_code_are_ignored(self, tmp_path):
        body = "Use `[x](https://bad.invalid)` literally.\n\n```\n[y](https://bad.invalid/2)\n```\n"
        calls = []
        report = check(tmp_path, make_doc(body=body), fetcher=ok_fetcher(calls))
        assert report["ok"], report
        assert calls == [SOURCE]

    def test_relative_links_must_stay_inside_and_be_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "my file.md").write_text("x")
        body = ("[a](/etc/passwd) [b](../../../../../../etc/hosts) [c](.) [d](sub)\n\n"
                "[e](sub/my%20file.md) [f](sub/my%20file.md#x)\n")
        report = check(tmp_path, make_doc(body=body))
        messages = [e["message"] for e in report["errors"]]
        assert rules(report) == ["links"] * 4
        assert any("absolute path" in m and "/etc/passwd" in m for m in messages)
        assert any("leaves the repository" in m for m in messages)
        assert sum("does not exist" in m for m in messages) == 2  # '.' and a directory

    def test_symlink_out_of_the_tree_is_refused(self, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "link.md").symlink_to(outside)
        report = cld.check_file(write(docs, make_doc(body="[x](link.md)\n")), today=TODAY)
        assert rules(report) == ["links"] and "leaves the repository" in report["errors"][0]["message"]

    def test_link_extraction_covers_headings_titles_and_parens(self, tmp_path):
        calls = []
        body = (
            "# [Broken](https://example.org/missing)\n\n"
            "See [x](https://example.org/single 'label') and [y](https://example.org/paren (label)).\n\n"
            "Also [Valid](https://en.wikipedia.org/wiki/Foo_(bar)) and [z](<https://example.org/angle>).\n"
        )
        check(tmp_path, make_doc(body=body), fetcher=ok_fetcher(calls))
        assert set(calls) >= {"https://example.org/missing", "https://example.org/single",
                              "https://example.org/paren", "https://en.wikipedia.org/wiki/Foo_(bar)",
                              "https://example.org/angle"}

    def test_slow_fetcher_hits_the_deadline(self, tmp_path, monkeypatch):
        import time as _time
        monkeypatch.setattr(cld, "URL_DEADLINE_SECONDS", 0.05)

        def slow(url):
            _time.sleep(0.5)
            return 200
        report = check(tmp_path, make_doc(), fetcher=slow)
        assert rules(report) == ["links"] and "TimeoutError" in report["errors"][0]["message"]

    def test_spent_run_budget_reports_unchecked_urls(self, tmp_path):
        meta, body, first, _ = cld.split_front_matter(make_doc())
        errors, checked = cld.check_links(tmp_path / "d.md", meta, [], ok_fetcher(), budget=cld._Budget(-1))
        assert checked == [] and "time budget" in errors[0]["message"]

    def test_url_cap(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cld, "MAX_URLS_PER_FILE", 2)
        body = "".join(f"[l](https://example.org/{i}) " for i in range(3)) + "\n"
        calls = []
        report = check(tmp_path, make_doc(body=body), fetcher=ok_fetcher(calls))
        assert rules(report) == ["links"]
        assert len(calls) == 2


class _Response(io.BytesIO):
    def __init__(self, status):
        super().__init__(b"body")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestHttpStatus:
    def _http_error(self, code):
        return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b""))

    def test_head_success_skips_get(self):
        methods = []

        def urlopen(request, timeout):
            methods.append((request.get_method(), timeout))
            return _Response(200)

        with mock.patch.object(cld, "_open", urlopen):
            assert cld.http_status("https://example.org") == 200
        assert methods == [("HEAD", 10)]

    def test_head_refused_falls_back_to_get(self):
        methods = []

        def urlopen(request, timeout):
            methods.append(request.get_method())
            if request.get_method() == "HEAD":
                raise self._http_error(405)
            return _Response(200)

        with mock.patch.object(cld, "_open", urlopen):
            assert cld.http_status("https://example.org") == 200
        assert methods == ["HEAD", "GET"]

    def test_head_network_error_falls_back_to_get(self):
        def urlopen(request, timeout):
            if request.get_method() == "HEAD":
                raise urllib.error.URLError("reset")
            raise self._http_error(404)

        with mock.patch.object(cld, "_open", urlopen):
            assert cld.http_status("https://example.org") == 404

    def test_both_fail_raises(self):
        def urlopen(request, timeout):
            raise urllib.error.URLError("dns")

        with mock.patch.object(cld, "_open", urlopen):
            with pytest.raises(urllib.error.URLError):
                cld.http_status("https://example.org")

    @pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "::1", "fd00::1",
                                         "::ffff:127.0.0.1", "0.0.0.0", "100.64.0.1"])
    def test_non_public_targets_are_refused_before_any_request(self, monkeypatch, address):
        monkeypatch.setattr(cld, "_resolve", lambda host, port: [address])

        def urlopen(request, timeout):
            raise AssertionError("must not connect")

        with mock.patch.object(cld, "_open", urlopen):
            with pytest.raises(ValueError):
                cld.http_status("http://internal.example/private")

    @pytest.mark.parametrize("url", ["ftp://example.org/x", "file:///etc/passwd", "http:///nohost"])
    def test_non_http_targets_are_refused(self, url):
        with pytest.raises(ValueError):
            cld.check_url_target(url)

    def test_redirects_are_checked_and_capped(self, monkeypatch):
        handler = cld._SafeRedirect()
        req = urllib.request.Request("https://example.org/a")
        for target in ("ftp://example.org/x", "file:///etc/passwd"):
            with pytest.raises(urllib.error.URLError):
                handler.redirect_request(req, None, 302, "Found", {}, target)
        monkeypatch.setattr(cld, "_resolve", lambda host, port: ["127.0.0.1"] if host == "evil.example"
                            else ["93.184.216.34"])
        with pytest.raises(urllib.error.URLError):
            handler.redirect_request(req, None, 302, "Found", {}, "http://evil.example/private")
        assert handler.redirect_request(req, None, 302, "Found", {}, "https://example.org/b") is not None
        assert cld._SafeRedirect.max_redirections == cld.MAX_REDIRECTS == 5


# --------------------------------------------------------------------------
# Rule 4: citations
# --------------------------------------------------------------------------

class TestCitations:
    def test_uncited_number_fails(self, tmp_path):
        body = "Intro line.\n\nThe API allows 5000 requests per hour.\n"
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["citations"]
        assert report["errors"][0]["line"] == 12
        assert "5000" in report["errors"][0]["message"]

    def test_uncited_date_fails(self, tmp_path):
        body = "The policy changed on 2026-03-01.\n"
        assert rules(check(tmp_path, make_doc(body=body))) == ["citations"]

    def test_citation_in_same_paragraph_passes(self, tmp_path):
        body = (
            "The API allows 5000 requests per hour.\n"
            "That figure comes from [the docs](https://example.org/docs).\n"
        )
        assert check(tmp_path, make_doc(body=body))["ok"]

    def test_citation_in_another_paragraph_does_not_count(self, tmp_path):
        body = "Source: [docs](https://example.org/docs).\n\nIt allows 5000 requests.\n"
        assert rules(check(tmp_path, make_doc(body=body))) == ["citations"]

    def test_each_list_item_needs_its_own_citation(self, tmp_path):
        body = (
            "- Limit is 60 per hour, per [docs](https://example.org/a).\n"
            "- Search is 30 per minute.\n"
        )
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["citations"]
        assert "30 per minute" in report["errors"][0]["message"]

    def test_link_inside_html_comment_is_not_a_citation(self, tmp_path):
        body = "The quota is 5000 requests. <!-- [proof](https://example.org/docs) -->\n"
        assert rules(check(tmp_path, make_doc(body=body))) == ["citations"]
        body = ("<!--\n[proof]: https://example.org/docs\n-->\n\n"
                "The quota is 5000 requests [proof].\n")
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["citations"] and report["errors"][0]["line"] == 14

    @pytest.mark.parametrize("opener,closer", [
        ("Use `<!--`.", "End with `-->`."),
        ("Use ``<!-- with a `backtick` ``.", "End with ``-->``."),
        ("Use `a multiline\nliteral <!-- example`.", "End with `-->`."),
        ("```html\n<!-- example\n```", "```html\n-->\n```"),
        ("~~~html\n<!-- example\n~~~", "~~~html\n-->\n~~~"),
        ("````html\n<!-- example\n```\n````", "```html\n-->\n```"),
    ])
    def test_code_comment_openers_do_not_hide_claims_or_dead_links(self, tmp_path, opener, closer):
        claim = "The quota is 5000 requests per hour."
        body = f"{opener}\n\n{claim}\n\nSee [docs](https://example.org/gone).\n\n{closer}\n"
        text = make_doc(body=body)
        calls = []

        def fetch(url):
            calls.append(url)
            return 404 if url.endswith("/gone") else 200

        report = check(tmp_path, text, fetcher=fetch)
        assert rules(report) == ["links", "citations"]
        assert calls == [SOURCE, "https://example.org/gone"]
        assert report["errors"][1]["line"] == text.splitlines().index(claim) + 1
        assert "5000" in report["errors"][1]["message"]

    def test_code_markers_inside_real_html_comments_do_not_hide_following_prose(self, tmp_path):
        body = ("<!--\nAn unmatched ` and a fence:\n```html\n"
                "Hidden 9000 and [hidden](https://example.org/hidden).\n-->\n\n"
                "Visible quota is 5000.\n\nSee [gone](https://example.org/gone).\n")
        report = check(tmp_path, make_doc(body=body),
                       fetcher=lambda url: 404 if url.endswith("/gone") else 200)
        assert rules(report) == ["links", "citations"]
        assert report["checked_urls"] == [SOURCE, "https://example.org/gone"]
        assert "5000" in report["errors"][1]["message"]

    @pytest.mark.parametrize("block", ["```html\n<!--\n```", "<!--\nHidden example.\n-->"])
    def test_inline_code_does_not_cross_block_boundaries(self, tmp_path, block):
        body = (f"Unmatched ` inline opener\n{block}\nVisible quota is 5000.\n\n"
                "See [gone](https://example.org/gone).\n"
                "```html\n-->\n```\nFinal ` token\n")
        report = check(tmp_path, make_doc(body=body),
                       fetcher=lambda url: 404 if url.endswith("/gone") else 200)
        assert rules(report) == ["links", "citations"]
        assert report["checked_urls"] == [SOURCE, "https://example.org/gone"]

    def test_relative_link_is_not_a_citation(self, tmp_path):
        (tmp_path / "other.md").write_text("x")
        body = "There are 12 channels, see [list](other.md).\n"
        assert rules(check(tmp_path, make_doc(body=body))) == ["citations"]

    def test_headings_code_and_url_digits_are_not_claims(self, tmp_path):
        body = (
            "# Notes for 2026\n\n"
            "Run `python3.11 -m pytest` first.\n\n"
            "```\nexit 1\n```\n\n"
            "Read [the guide](https://example.org/v2/page-3) for background.\n\n"
            "No numbers here at all.\n"
        )
        report = check(tmp_path, make_doc(body=body))
        assert report["ok"], report

    def test_only_numeric_sentences_are_reported(self, tmp_path):
        body = "This is fine. But 42 is a claim. So is 7.\n"
        report = check(tmp_path, make_doc(body=body))
        assert len(report["errors"]) == 2

    def test_longer_fence_hides_shorter_inner_fence(self, tmp_path):
        body = "````markdown\n```\n````\nThe limit is 5000 with no citation.\n"
        report = check(tmp_path, make_doc(body=body))
        assert rules(report) == ["citations"] and "5000" in report["errors"][0]["message"]
        inner = "````markdown\n```\nThe limit is 5000 inside the example.\n```\n````\n"
        assert check(tmp_path, make_doc(body=inner))["ok"]

    def test_ordered_list_markers_are_not_claims(self, tmp_path):
        prose = "1. Batch reads where you can.\n2. Prefer GraphQL.\n10) Cache results.\n"
        assert check(tmp_path, make_doc(body=prose))["ok"]
        claim = "1. Limit is 60/hour.\n"
        report = check(tmp_path, make_doc(body=claim))
        assert rules(report) == ["citations"] and "60/hour" in report["errors"][0]["message"]

    def test_reference_links_and_footnotes_cite(self, tmp_path):
        body = (
            "There are 3 agents [according to docs][ref].\n\n"
            "And 4 more per [the source][].\n\n"
            "Also 5 in [Docs].\n\n"
            "Finally 6 here[^1].\n\n"
            "[ref]: https://example.org/source\n"
            "[the source]: https://example.org/source\n"
            "[docs]: https://example.org/source\n"
            "[^1]: See https://example.org/source for details.\n"
        )
        report = check(tmp_path, make_doc(body=body))
        assert report["ok"], report
        unresolved = "There are 3 agents [according to docs][nope].\n\n[local]: other.md\n"
        assert "citations" in rules(check(tmp_path, make_doc(body=unresolved)))

    def test_definition_inside_paragraph_counts(self, tmp_path):
        body = "It has 3 parts.\n[ref]: https://example.org/source\n"
        assert "citations" not in rules(check(tmp_path, make_doc(body=body)))

    def test_escaped_bracket_is_not_a_citation(self, tmp_path):
        body = "There are 3 agents \\[fake](https://example.org/source).\n"
        assert rules(check(tmp_path, make_doc(body=body))) == ["citations"]


# --------------------------------------------------------------------------
# CLI and README example
# --------------------------------------------------------------------------

def _readme_example():
    text = README.read_text()
    match = re.search(r"~~~markdown\n(.*?)\n~~~", text, re.DOTALL)
    assert match, "docs/living/README.md must carry one inline example"
    return match.group(1) + "\n"


class TestCli:
    def test_pass_exit_zero_with_json_report(self, tmp_path, capsys):
        path = write(tmp_path, make_doc())
        code = cld.main([str(path), "--offline", "--today", TODAY.isoformat()])
        report = json.loads(capsys.readouterr().out)
        assert code == 0
        assert report["schema"] == cld.SCHEMA
        assert report["ok"] is True
        assert report["files"][0]["ok"] is True

    def test_fail_exit_one_with_json_report(self, tmp_path, capsys):
        path = write(tmp_path, make_doc(drop=("title",)))
        code = cld.main([str(path), "--offline", "--today", TODAY.isoformat()])
        report = json.loads(capsys.readouterr().out)
        assert code == 1
        assert report["ok"] is False
        assert report["files"][0]["errors"][0]["rule"] == "front_matter"

    def test_offline_flag_beats_injected_fetcher(self, tmp_path, capsys):
        def boom(url):
            raise AssertionError("network used while --offline")
        path = write(tmp_path, make_doc())
        assert cld.main([str(path), "--offline", "--today", TODAY.isoformat()], fetcher=boom) == 0

    def test_online_uses_fetcher(self, tmp_path, capsys):
        calls = []
        path = write(tmp_path, make_doc())
        assert cld.main([str(path), "--today", TODAY.isoformat()], fetcher=ok_fetcher(calls)) == 0
        assert calls == [SOURCE]

    def test_directory_skips_readme(self, tmp_path, capsys):
        write(tmp_path, "not a living doc", name="README.md")
        write(tmp_path, make_doc(), name="topic.md")
        assert cld.main([str(tmp_path), "--offline", "--today", TODAY.isoformat()]) == 0
        report = json.loads(capsys.readouterr().out)
        assert [Path(f["file"]).name for f in report["files"]] == ["topic.md"]

    def test_bad_today_is_a_usage_error(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            cld.main([str(tmp_path), "--today", "soon"])
        assert exc.value.code == 2

    def test_subprocess_offline(self, tmp_path):
        path = write(tmp_path, make_doc(body="It has 3 parts.\n"))
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_living_doc.py"), str(path),
             "--offline", "--today", TODAY.isoformat()],
            capture_output=True, text=True, cwd=str(tmp_path),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert result.returncode == 1
        assert json.loads(result.stdout)["files"][0]["errors"][0]["rule"] == "citations"

    def test_readme_example_passes(self, tmp_path):
        example = _readme_example()
        meta, _, _, _ = cld.split_front_matter(example)
        today = dt.date.fromisoformat(meta["last_verified"])
        calls = []
        report = check(tmp_path, example, fetcher=ok_fetcher(calls), today=today)
        assert report["ok"], report
        assert calls == meta["sources"]

    def test_readme_example_uncited_claim_would_fail(self, tmp_path):
        example = _readme_example().replace(
            "batch reads where you can.", "batch reads where you can, about 80 at a time."
        )
        meta, _, _, _ = cld.split_front_matter(example)
        today = dt.date.fromisoformat(meta["last_verified"])
        assert rules(check(tmp_path, example, today=today)) == ["citations"]

    def test_checked_in_living_docs_have_valid_structure(self, capsys):
        """Every real doc passes offline except for freshness, which is time-bound.

        A guard for future docs: today docs/living holds only README.md, so
        the loop may be empty, but the directory must still have no stray
        files and collect_paths must pick up every top-level <slug>.md.
        """
        living = ROOT / "docs" / "living"
        expected = sorted(p for p in living.glob("*.md") if p.name != "README.md")
        assert cld.collect_paths([str(living)]) == expected
        assert cld.layout_reports([str(living)]) == []
        for path in expected:
            report = cld.check_file(path)
            assert set(rules(report)) <= {"freshness"}, report

    def test_nested_and_badly_named_files_fail_the_directory(self, tmp_path, capsys):
        write(tmp_path, make_doc(), name="good-topic.md")
        (tmp_path / "sub").mkdir()
        write(tmp_path / "sub", make_doc(body="It has 3 parts.\n"), name="hidden.md")
        write(tmp_path, make_doc(), name="Bad_Name.md")
        assert cld.main([str(tmp_path), "--offline", "--today", TODAY.isoformat()]) == 1
        report = json.loads(capsys.readouterr().out)
        layout = sorted(Path(f["file"]).name for f in report["files"]
                        if f["errors"] and f["errors"][0]["rule"] == "layout")
        assert layout == ["Bad_Name.md", "hidden.md"]

    def test_internal_errors_become_a_failing_report(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("bug")
        monkeypatch.setattr(cld, "check_citations", boom)
        report = check(tmp_path, make_doc())
        assert report["ok"] is False and rules(report) == ["internal"]


# --------------------------------------------------------------------------
# Intake forms are not actions
# --------------------------------------------------------------------------

def _form(name):
    """Parse the subset of an Issue Form these tests need."""
    text = (TEMPLATE_DIR / name).read_text()
    title = re.search(r'^title:\s*"([^"]*)"', text, re.M).group(1)
    labels = json.loads(re.search(r"^labels:\s*(\[.*\])\s*$", text, re.M).group(1))
    fields = re.findall(r"^\s+label:\s*(.+?)\s*$", text, re.M)
    return text, title, labels, fields


# The workflows that queue or apply actions. Factory tooling (foreman,
# worker, ...) may read factory:* labels; these two must never route an
# intake form INTO the inbox.
ACTION_QUEUEING = ("process-issues.yml", "process-inbox.yml")


FORMS = ["request.yml", "living_doc.yml"]


class TestIntakeForms:
    def test_request_form_shape(self):
        text, title, labels, fields = _form("request.yml")
        assert title.startswith("[Request]")
        assert labels == ["factory:request", "factory:backlog"]
        for needed in ("What do you want?", "Why do you want it?",
                       "How will you check it is done?", "Deadline (optional)"):
            assert needed in fields
        assert re.search(r"id: deadline\n(?:.*\n)*?\s+required: false", text)

    def test_living_doc_form_shape(self):
        _, title, labels, fields = _form("living_doc.yml")
        assert title.startswith("[Living doc]")
        assert all(label.startswith("factory:") for label in labels)
        for needed in ("Topic", "Scope", "Refresh cadence (days)", "Required sources"):
            assert needed in fields

    @pytest.mark.parametrize("name", FORMS)
    def test_labels_and_title_are_not_actions(self, name):
        from actions import HANDLERS
        text, title, labels, _ = _form(name)
        action_names = set(HANDLERS) | {a.replace("_", "-") for a in HANDLERS}
        for label in labels:
            assert label not in action_names
            assert not label.startswith("action:")
        prefix = title.strip().strip("[]").lower()
        assert prefix.replace(" ", "_") not in HANDLERS
        assert "render: json" not in text
        assert '"action"' not in text

    @pytest.mark.parametrize("name", FORMS)
    def test_action_queueing_workflows_skip_form_labels_and_prefix(self, name):
        """process-issues.yml's job `if:` excludes every form label and the
        title prefix (labels missing from the repository are dropped, so the
        prefix guard is needed too); process-inbox.yml never mentions them."""
        _, title, labels, _ = _form(name)
        prefix = title.strip()
        text = (WORKFLOW_DIR / "process-issues.yml").read_text()
        condition = text.split("if: >-", 1)[1].split("steps:", 1)[0]
        for label in labels:
            if label == "factory:backlog":
                continue  # shared with factory cards; the request label and prefix suffice
            assert f"!contains(github.event.issue.labels.*.name, '{label}')" in condition, label
            # every mention of the label in this workflow is a negation
            assert text.count(f"'{label}'") == condition.count(f"!contains(github.event.issue.labels.*.name, '{label}')")
        assert f"!startsWith(github.event.issue.title, '{prefix}')" in condition
        inbox = (WORKFLOW_DIR / "process-inbox.yml").read_text().lower()
        for label in labels:
            assert label.lower() not in inbox
        assert prefix.lower() not in inbox

    @pytest.mark.parametrize("name", FORMS)
    def test_filled_form_queues_no_delta(self, name, tmp_path):
        """A submitted form, rendered as GitHub renders Issue Forms, is never queued."""
        _, title, labels, fields = _form(name)
        answer = "A page listing 3 verified answers by 2026-12-31, e.g. {see notes}."
        body = "\n\n".join(f"### {field}\n\n{answer}" for field in fields) + "\n"
        self._assert_not_queued(title, labels, body, tmp_path)

    @pytest.mark.parametrize("name", FORMS)
    @pytest.mark.parametrize("fenced", [
        "```bash\npython3 scripts/check_living_doc.py docs/living --offline\n```",
        '```json\n{"action": "heartbeat", "payload": {}}\n```',
        '```json\n{"example": true}\n```',
    ])
    def test_filled_form_with_code_fences_queues_no_delta(self, name, fenced, tmp_path):
        """Fenced commands, fenced JSON, even a fenced action: still not queued."""
        _, title, labels, fields = _form(name)
        body = "\n\n".join(f"### {field}\n\n{fenced}" for field in fields) + "\n"
        self._assert_not_queued(title, labels, body, tmp_path)
        # the title prefix alone is enough (a label the repo lacks is dropped)
        self._assert_not_queued(title, [], body, tmp_path)

    @staticmethod
    def _assert_not_queued(title, labels, body, tmp_path):
        event = {
            "issue": {
                "number": 4242,
                "title": f"{title}something useful",
                "body": body,
                "user": {"login": "reader", "id": 77},
                "labels": [{"name": label} for label in labels],
            }
        }
        state = tmp_path / "state"
        state.mkdir(exist_ok=True)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "process_issues.py")],
            input=json.dumps(event), capture_output=True, text=True, cwd=str(ROOT),
            env={**os.environ, "STATE_DIR": str(state), "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert result.returncode == 0, result.stderr
        assert "nothing to queue" in result.stdout
        assert not list(state.rglob("*.json"))
        assert "Welcome" not in result.stdout + result.stderr


class TestWorkflow:
    def test_living_docs_workflow_is_event_triggered_and_read_only(self):
        text = (WORKFLOW_DIR / "living-docs.yml").read_text()
        assert "schedule:" not in text
        assert "pull_request_target" not in text
        assert re.search(r"^  pull_request:\n    paths:\n      - 'docs/living/\*\*'", text, re.M)
        assert "workflow_dispatch:" in text
        assert "secrets." not in text
        assert "persist-credentials: false" in text
        perms = re.findall(r"permissions:\n((?:\s+\w[\w-]*: \w+\n)+)", text)
        assert perms
        for block in perms:
            assert set(re.findall(r":\s*(\w+)", block)) == {"read"}
        assert "${{ inputs" not in text.split("run: |", 1)[1]
        assert "scripts/check_living_doc.py docs/living" in text
