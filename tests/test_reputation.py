"""Reputation from verified work, and the flagged newsletter / trending hooks.

Covers scripts/compute_reputation.py (docs/reputation.json, schema
rappterbook-reputation/1), the opt-in 'Verified this week' newsletter
section (NEWSLETTER_VERIFIED) and the opt-in trending boost
(TRENDING_VERIFIED_BOOST). gh is always mocked; nothing here touches GitHub.
"""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import answer_qa  # noqa: E402
import compute_reputation as rep  # noqa: E402
import verifications  # noqa: E402

REPO = "kody-w/rappterbook"
SERVICES = {"kody-w", "rappter1", "rappter2-ux"}
BASE_REF = "ake-pattern-round1"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def issue(number, labels=("factory:collected",), state="CLOSED", reason="COMPLETED",
          closers=(), title="Fix the thing", **extra):
    data = {
        "number": number, "title": title, "state": state, "stateReason": reason,
        "labels": [{"name": l} for l in labels], "closedAt": "2026-10-10T12:00:00Z",
        "url": f"https://github.com/{REPO}/issues/{number}",
        "closedByPullRequestsReferences": [
            {"number": n, "url": f"https://github.com/{REPO}/pull/{n}"} for n in closers],
    }
    data.update(extra)
    return data


def pr(number, author="outside-dev", body="", merged=True, closes=()):
    return {
        "number": number, "author": {"login": author}, "body": body,
        "state": "MERGED" if merged else "CLOSED",
        "mergedAt": "2026-10-10T11:00:00Z" if merged else None,
        "url": f"https://github.com/{REPO}/pull/{number}",
        "closingIssuesReferences": [
            {"number": n, "url": f"https://github.com/{REPO}/issues/{n}"} for n in closes],
    }


def verify_block(subject, passed=True, notes="ran it", env="python-3.11/linux"):
    payload = {"action": "verify", "subject": subject, "environment": env, "passed": passed}
    if notes:
        payload["notes"] = notes
    return "Tried it.\n\n```json\n" + json.dumps(payload) + "\n```\n"


def comment(body, login, at="2026-10-09T10:00:00Z", cid="C1"):
    return {"id": cid, "body": body, "author_login": login, "created_at": at}


POST_BODY = "*Posted by **zion-coder-02***\n\n---\n\nenvironment: python-3.11\n\n```python\nprint(1)\n```"


def discussion(number=101, body=POST_BODY, author="kody-w", comments=(), title="A working fix"):
    return {"number": number, "title": title, "author_login": author, "body": body,
            "url": f"https://github.com/{REPO}/discussions/{number}", "comments": list(comments)}


def build(issues=(), prs=(), discussions=()):
    return rep.build_reputation(list(issues), list(prs), list(discussions), repo=REPO, services=SERVICES)


# ---------------------------------------------------------------------------
# Cards shipped
# ---------------------------------------------------------------------------

class TestCards:
    def test_shipped_card_credits_pr_author(self):
        doc = build([issue(1, closers=[10])], [pr(10, author="alice")])
        assert doc["shipped_cards"][0]["agent"] == "alice"
        assert doc["shipped_cards"][0]["via"] == "pr_author"
        assert doc["agents"]["alice"]["cards_shipped"] == 1
        assert doc["agents"]["alice"]["cards"] == [1]

    def test_agent_line_overrides_author(self):
        body = "Fixes #1\n\nAgent: zion-coder-02\n"
        doc = build([issue(1, closers=[10])], [pr(10, author="kody-w", body=body)])
        card = doc["shipped_cards"][0]
        assert (card["agent"], card["via"], card["pr_author"]) == ("zion-coder-02", "agent_line", "kody-w")
        assert card["pr_author_is_service"] is True
        assert "kody-w" not in doc["agents"]

    def test_agent_line_inside_code_fence_is_ignored(self):
        body = "Example:\n```\nAgent: mallory\n```\n"
        doc = build([issue(1, closers=[10])], [pr(10, author="alice", body=body)])
        assert doc["shipped_cards"][0]["agent"] == "alice"

    def test_conflicting_agent_lines_fall_back_to_author(self):
        body = "Agent: a1\nAgent: b2\n"
        doc = build([issue(1, closers=[10])], [pr(10, author="alice", body=body)])
        assert doc["shipped_cards"][0]["agent"] == "alice"

    def test_agent_line_with_unsafe_id_is_ignored(self):
        body = "Agent: $(rm -rf /)\n"
        assert rep.agent_line(body) == ""
        assert rep.agent_line("Agent: `zion-x_1`") == "zion-x_1"

    def test_closing_issues_reference_path(self):
        doc = build([issue(2)], [pr(11, author="bob", closes=[2])])
        assert [c["issue"] for c in doc["shipped_cards"]] == [2]

    def test_unmerged_pr_does_not_ship(self):
        doc = build([issue(1, closers=[10])], [pr(10, merged=False)])
        assert doc["shipped_cards"] == []
        assert doc["totals"]["cards_shipped"] == 0

    def test_not_planned_does_not_ship(self):
        doc = build([issue(1, reason="NOT_PLANNED", closers=[10])], [pr(10)])
        assert doc["shipped_cards"] == []

    def test_open_issue_does_not_ship(self):
        doc = build([issue(1, state="OPEN", closers=[10])], [pr(10)])
        assert doc["shipped_cards"] == []

    def test_non_factory_issue_ignored(self):
        doc = build([issue(1, labels=("bug",), closers=[10])], [pr(10)])
        assert doc["shipped_cards"] == [] and doc["agents"] == {}

    def test_agent_line_from_an_ordinary_author_is_ignored(self):
        doc = build([issue(1, closers=[10])], [pr(10, author="alice", body="Fixes #1\n\nAgent: mallory\n")])
        card = doc["shipped_cards"][0]
        assert (card["agent"], card["via"]) == ("alice", "pr_author")

    def test_agent_line_inside_html_comment_is_ignored(self):
        body = "Fixes #1\n\n<!--\nAgent: mallory\n-->\n"
        assert rep.agent_line(body) == ""
        assert rep.agent_line("<!-- Agent: mallory -->\nAgent: zion-a\n") == "zion-a"
        doc = build([issue(1, closers=[10])], [pr(10, author="kody-w", body=body)])
        assert doc["shipped_cards"][0]["agent"] == "kody-w"

    def test_foreman_card_without_label_ships_with_worker_agent_line(self):
        card = issue(5, labels=(), title="[Foreman] Add a retry", closers=[20])
        worker_pr = pr(20, author="app/github-actions", body="Closes #5\n\nAgent: zion-worker-01\n")
        doc = build([card], [worker_pr])
        shipped = doc["shipped_cards"][0]
        assert (shipped["issue"], shipped["agent"], shipped["via"]) == (5, "zion-worker-01", "agent_line")
        assert shipped["pr_author"] == "github-actions[bot]"
        no_line = build([card], [pr(20, author="app/github-actions", body="Closes #5")])
        assert no_line["shipped_cards"][0]["agent"] == "github-actions[bot]"

    @pytest.mark.parametrize("reason", ["DUPLICATE", "NOT_PLANNED", "REOPENED"])
    def test_only_completed_closures_ship(self, reason):
        doc = build([issue(1, reason=reason, closers=[10])], [pr(10)])
        assert doc["shipped_cards"] == []

    def test_issue_side_references_win_over_reverse_lookup(self):
        # the issue names PR 10 (not merged); PR 12 merely mentions it
        doc = build([issue(1, closers=[10])], [pr(10, merged=False), pr(12, closes=[1])])
        assert doc["shipped_cards"] == []

    @pytest.mark.parametrize("bad", [
        {"labels": 7}, {"assignees": 7}, {"closedByPullRequestsReferences": 7},
        {"closedAt": "0001-01-01T00:00:00+01:00"},
    ])
    def test_malformed_issue_fields_do_not_crash(self, bad, tmp_path):
        fixture = tmp_path / "in.json"
        card = issue(1, closers=[10], labels=("factory:bounced",))
        card.update(bad)
        fixture.write_text(json.dumps({"issues": [card], "pull_requests": [pr(10)],
                                       "discussions": [dict(discussion(), comments=7)]}))
        assert rep.main(["--input", str(fixture), "--stdout", "--repo", REPO]) == 0

    def test_foreign_repo_pr_ignored(self):
        card = issue(1)
        card["closedByPullRequestsReferences"] = [{"number": 10, "url": "https://github.com/evil/fork/pull/10"}]
        doc = build([card], [pr(10)])
        assert doc["shipped_cards"] == []

    def test_untrusted_title_is_cleaned(self):
        title = "Fix‮ evil\x1b[31m ghp_" + "a" * 30 + "\nsecond line"
        doc = build([issue(1, closers=[10], title=title)], [pr(10)])
        cleaned = doc["shipped_cards"][0]["title"]
        assert "‮" not in cleaned and "\x1b" not in cleaned and "\n" not in cleaned
        assert "ghp_" not in cleaned and "[REDACTED]" in cleaned


class TestBounces:
    def test_bounced_label_counts_and_credits_shipper(self):
        doc = build([issue(1, labels=("factory:collected", "factory:bounced"), closers=[10])],
                    [pr(10, author="alice")])
        assert doc["agents"]["alice"]["qa_bounces"] == 1
        assert doc["agents"]["alice"]["bounced_cards"] == [1]
        assert doc["agents"]["alice"]["cards_shipped"] == 1

    def test_reopened_count_from_timeline(self):
        doc = build([issue(1, closers=[10], reopenedCount=2)], [pr(10, author="alice")])
        assert doc["bounced_cards"][0]["reopened"] == 2
        assert doc["agents"]["alice"]["qa_bounces"] == 1

    def test_reopened_state_reason_counts(self):
        doc = build([issue(1, state="OPEN", reason="REOPENED", assignees=[{"login": "carol"}])])
        assert doc["bounced_cards"][0]["agent"] == "carol"
        assert doc["bounced_cards"][0]["via"] == "assignee"

    def test_unattributed_bounce(self):
        doc = build([issue(1, labels=("factory:bounced",), state="OPEN", reason="")])
        assert doc["bounced_cards"][0]["agent"] == rep.UNATTRIBUTED


# ---------------------------------------------------------------------------
# Verification votes
# ---------------------------------------------------------------------------

class TestVerifications:
    def subject(self):
        return verifications.content_id(POST_BODY)

    def test_outside_pass_vote_credits_byline_persona(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "outside-dev")])
        doc = build(discussions=[disc])
        row = doc["verified"][0]
        # one account vouching alone is recorded but is not "passing"
        assert (row["agent"], row["target"], row["pass_count"], row["passing"]) == \
            ("zion-coder-02", "post", 1, False)
        expected = verifications.score(
            {"schema": verifications.SCHEMA, "subjects": {self.subject(): {"outside-dev": {
                "schema": verifications.SCHEMA, "subject": self.subject(), "subject_kind": "post",
                "environment": "python-3.11/linux", "passed": True, "notes": "ran it",
                "verifier": "outside-dev", "at": "2026-10-09T10:00:00Z"}}}}, self.subject())
        assert row["score"] == expected["score"]
        stats = doc["agents"]["zion-coder-02"]["verification"]
        assert (stats["pass"], stats["fail"], stats["votes"]) == (1, 0, 1)
        assert stats["score"] == expected["score"]
        assert row["last_pass_at"] == "2026-10-09T10:00:00Z"

    def test_two_distinct_human_passes_make_a_subject_passing(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "outside-dev", cid="1"),
                                    comment(verify_block(self.subject()), "second-dev", cid="2")])
        row = build(discussions=[disc])["verified"][0]
        assert (row["pass_count"], row["passing"], row["verifiers"]) == (2, True, ["outside-dev", "second-dev"])

    def test_one_global_vote_per_verifier_per_subject(self):
        discs = [discussion(number=n, body="print(1)", author="alice",
                            comments=[comment(verify_block(verifications.content_id("print(1)")), "bob",
                                              cid=f"C{n}")])
                 for n in range(1, 21)]
        doc = build(discussions=discs)
        assert len(doc["verified"]) == 1
        row = doc["verified"][0]
        assert (row["discussion"], row["pass_count"], row["votes"]) == (1, 1, 1)
        stats = doc["agents"]["alice"]["verification"]
        assert (stats["votes"], stats["subjects"], stats["verifiers"]) == (1, 1, 1)
        assert stats["score"] == rep.wilson(1, 1)

    def test_agent_score_counts_each_verifier_once(self):
        comments = []
        for n in range(10):
            body = f"*— **zion-a***\n\nanswer number {n}"
            comments.append(comment(body, "kody-w", cid=f"A{n}"))
            comments.append(comment(verify_block(verifications.content_id(body)), "sock",
                                    at=f"2026-10-09T11:{n:02d}:00Z", cid=f"V{n}"))
        doc = build(discussions=[discussion(comments=comments)])
        stats = doc["agents"]["zion-a"]["verification"]
        assert (stats["pass"], stats["subjects"], stats["verifiers"], stats["verifiers_pass"]) == (10, 10, 1, 1)
        assert stats["score"] == rep.wilson(1, 1)
        assert stats["passing_subjects"] == 0

    def test_same_instant_pass_and_fail_resolve_to_fail_in_any_order(self):
        subj = self.subject()
        votes = [comment(verify_block(subj), "bob", at="2026-10-09T10:00:00Z", cid="C1"),
                 comment(verify_block(subj, passed=False, notes="broke"), "bob", at="2026-10-09T10:00:00Z",
                         cid="C2")]
        for order in (votes, votes[::-1]):
            row = build(discussions=[discussion(comments=list(order))])["verified"][0]
            assert (row["pass_count"], row["fail_count"]) == (0, 1)

    def test_identical_bodies_credit_the_earliest_and_bar_every_copier(self):
        body = "the same code"
        subj = verifications.content_id(body)
        disc = discussion(body="question", author="carol", comments=[
            comment(body, "late", at="2026-10-09T09:00:00Z", cid="B"),
            comment(body, "early", at="2026-10-09T08:00:00Z", cid="A"),
            comment(verify_block(subj), "late", at="2026-10-09T10:00:00Z", cid="V1"),
            comment(verify_block(subj), "outside-dev", at="2026-10-09T10:00:00Z", cid="V2"),
        ])
        doc = build(discussions=[disc])
        row = doc["verified"][0]
        assert (row["agent"], row["comment_id"], row["pass_count"]) == ("early", "A", 1)
        assert doc["totals"]["dropped_invalid"] == 1  # 'late' owns a copy: self-vote

    def test_incomplete_snapshot_is_never_passing(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "outside-dev", cid="1"),
                                    comment(verify_block(self.subject()), "second-dev", cid="2")])
        disc["reply_bodies_complete"] = False
        doc = build(discussions=[disc])
        row = doc["verified"][0]
        assert (row["passing"], row["incomplete"]) == (False, True)
        assert doc["totals"]["incomplete_discussions"] == 1 and doc["totals"]["incomplete_subjects"] == 1

    def test_service_login_votes_are_not_counted(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "rappter1")])
        doc = build(discussions=[disc])
        assert doc["verified"] == []
        assert doc["totals"]["dropped_service_login"] == 1

    def test_automation_votes_are_not_counted(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "github-actions[bot]")])
        doc = build(discussions=[disc])
        assert doc["verified"] == [] and doc["totals"]["dropped_automation"] == 1

    def test_self_vote_rejected(self):
        body = "my code"
        disc = discussion(body=body, author="alice",
                          comments=[comment(verify_block(verifications.content_id(body)), "Alice")])
        doc = build(discussions=[disc])
        assert doc["verified"] == [] and doc["totals"]["dropped_invalid"] == 1

    def test_byline_owner_self_vote_rejected(self):
        disc = discussion(comments=[comment(verify_block(self.subject()), "zion-coder-02")])
        doc = build(discussions=[disc])
        assert doc["verified"] == []

    def test_vote_for_other_threads_content_is_dropped(self):
        other = verifications.content_id("someone else's post")
        disc = discussion(comments=[comment(verify_block(other), "outside-dev")])
        doc = build(discussions=[disc])
        assert doc["verified"] == [] and doc["totals"]["dropped_unbound"] == 1

    def test_vote_without_timestamp_is_dropped(self):
        c = comment(verify_block(self.subject()), "outside-dev")
        del c["created_at"]
        doc = build(discussions=[discussion(comments=[c])])
        assert doc["verified"] == [] and doc["totals"]["dropped_invalid"] == 1

    def test_answer_comment_can_be_verified(self):
        answer = "*— **zion-helper-01***\n\nUse `sqlite3.connect(..., timeout=30)`."
        disc = discussion(comments=[
            comment(answer, "kody-w", cid="A1"),
            comment(verify_block(verifications.content_id(answer)), "outside-dev",
                    at="2026-10-09T11:00:00Z", cid="V1"),
            comment(verify_block(verifications.content_id(answer)), "second-dev",
                    at="2026-10-09T11:30:00Z", cid="V2"),
        ])
        doc = build(discussions=[disc])
        row = doc["verified"][0]
        assert (row["target"], row["comment_id"], row["agent"]) == ("comment", "A1", "zion-helper-01")
        assert rep.passing_discussions(doc)[101]["target"] == "comment"

    def test_fail_majority_is_not_passing(self):
        subj = self.subject()
        disc = discussion(comments=[
            comment(verify_block(subj), "v1", cid="1"),
            comment(verify_block(subj, passed=False, notes="ImportError"), "v2", cid="2"),
            comment(verify_block(subj, passed=False, notes="ImportError"), "v3", cid="3"),
        ])
        doc = build(discussions=[disc])
        row = doc["verified"][0]
        assert (row["pass_count"], row["fail_count"], row["passing"]) == (1, 2, False)
        assert rep.passing_discussions(doc) == {}

    def test_latest_vote_per_login_wins(self):
        subj = self.subject()
        disc = discussion(comments=[
            comment(verify_block(subj, passed=False, notes="broke"), "v1", at="2026-10-09T10:00:00Z", cid="1"),
            comment(verify_block(subj), "v1", at="2026-10-09T12:00:00Z", cid="2"),
        ])
        row = build(discussions=[disc])["verified"][0]
        assert (row["pass_count"], row["fail_count"]) == (1, 0)

    # -- platform votes from answer-qa (docs/VERIFICATIONS.md, "Platform identity")

    ANSWER = "*— **zion-coder-01***\n\nenvironment: python-3.11/linux\n\n```python\nprint(1)\n```"

    def platform_reply(self, comment_id="DC_ans", code="print(1)", passed=True):
        result = {"schema": answer_qa.RESULT_SCHEMA, "status": "ran", "comment_id": comment_id,
                  "discussion_number": 101, "runtime": "python-3.11", "image": "python:3.11-slim",
                  "content_id": verifications.content_id(code), "exit_code": 0 if passed else 1,
                  "timed_out": False, "duration_s": 0.1, "stdout": "1\n", "stderr": "",
                  "stdout_truncated": False, "stderr_truncated": False}
        return answer_qa.render_reply(result)

    def platform_disc(self, reply_login="github-actions", reply=None, answer=None, number=101):
        return discussion(number=number, body="How do I print?", author="carol", comments=[
            comment(answer or self.ANSWER, "kody-w", at="2026-10-09T09:00:00Z", cid="DC_ans"),
            comment(reply or self.platform_reply(), reply_login, at="2026-10-09T09:05:00Z", cid="DC_rep"),
        ])

    def test_platform_vote_counts_under_sandbox_and_credits_the_answer(self):
        doc = build(discussions=[self.platform_disc()])
        row = doc["verified"][0]
        assert (row["target"], row["comment_id"], row["agent"]) == ("comment", "DC_ans", "zion-coder-01")
        assert row["subject"] == verifications.content_id("print(1)")
        assert (row["platform"], row["passing"], row["verifiers"]) == ("pass", True, [answer_qa.PLATFORM_VERIFIER])
        assert doc["totals"]["platform_votes_counted"] == 1 and doc["totals"]["dropped_unbound"] == 0
        assert rep.passing_discussions(doc)[101]["target"] == "comment"
        failed = build(discussions=[self.platform_disc(reply=self.platform_reply(passed=False))])
        assert (failed["verified"][0]["platform"], failed["verified"][0]["passing"]) == ("fail", False)

    def test_platform_vote_also_counts_with_rest_login(self):
        doc = build(discussions=[self.platform_disc(reply_login="github-actions[bot]")])
        assert doc["totals"]["platform_votes_counted"] == 1

    @pytest.mark.parametrize("case", ["other_bot", "edited_answer", "foreign_comment", "quoted_marker"])
    def test_platform_vote_binding_is_strict(self, case):
        kwargs = {}
        if case == "other_bot":
            kwargs["reply_login"] = "some-app[bot]"
        elif case == "edited_answer":
            kwargs["answer"] = self.ANSWER.replace("print(1)", "print(2)")
        elif case == "foreign_comment":
            kwargs["reply"] = self.platform_reply(comment_id="DC_elsewhere")
        else:
            kwargs["reply"] = "quoting:\n" + self.platform_reply()
        doc = build(discussions=[self.platform_disc(**kwargs)])
        assert doc["totals"]["platform_votes_counted"] == 0
        assert all(r["platform"] == "" for r in doc["verified"])

    def test_wilson_matches_library(self):
        for passes, n in ((1, 1), (8, 10), (80, 100), (0, 5), (0, 0)):
            assert rep.wilson(passes, n) == round(verifications._wilson_lower_bound(passes, n), 6)


# ---------------------------------------------------------------------------
# Document shape and determinism
# ---------------------------------------------------------------------------

def sample_inputs():
    subj = verifications.content_id(POST_BODY)
    issues = [issue(1, closers=[10]), issue(2, labels=("factory:bounced",), closers=[11]),
              issue(3, labels=("bug",))]
    prs = [pr(10, author="alice"), pr(11, author="kody-w", body="Agent: zion-coder-02")]
    discs = [discussion(comments=[comment(verify_block(subj), "outside-dev", cid="C1"),
                                  comment(verify_block(subj), "second-dev", cid="C2")]),
             discussion(number=7, body="no votes here", author="bob")]
    return issues, prs, discs


class TestDocument:
    def test_schema_and_note(self):
        doc = build(*sample_inputs())
        assert doc["schema"] == "rappterbook-reputation/1"
        assert "aggregate" in doc["note"] and "kody-w" in doc["note"]
        assert doc["service_logins"] == sorted(SERVICES)

    def test_service_login_entries_are_marked(self):
        doc = build([issue(1, closers=[10])], [pr(10, author="kody-w")])
        assert doc["agents"]["kody-w"]["service_login"] is True

    def test_deterministic_regardless_of_input_order(self):
        issues, prs, discs = sample_inputs()
        first = rep.dumps(build(issues, prs, discs))
        second = rep.dumps(build(issues[::-1], prs[::-1], discs[::-1]))
        assert first == second
        assert first.endswith("\n")

    def test_cli_input_writes_file(self, tmp_path, capsys):
        issues, prs, discs = sample_inputs()
        fixture = tmp_path / "in.json"
        fixture.write_text(json.dumps({"issues": issues, "pull_requests": prs, "discussions": discs}))
        out = tmp_path / "docs" / "reputation.json"
        assert rep.main(["--input", str(fixture), "--out", str(out), "--repo", REPO]) == 0
        written = out.read_text()
        assert json.loads(written)["totals"]["cards_shipped"] == 2
        assert rep.main(["--input", str(fixture), "--out", str(out), "--repo", REPO]) == 0
        assert out.read_text() == written

    def test_cli_rejects_bad_input(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("[1, 2]")
        assert rep.main(["--input", str(bad), "--stdout"]) == 1
        assert rep.main(["--input", str(tmp_path / "missing.json"), "--stdout"]) == 1
        assert rep.main(["--input", str(bad), "--repo", "not a repo"]) == 1

    def test_load_reputation_rejects_other_schema(self, tmp_path):
        path = tmp_path / "r.json"
        path.write_text(json.dumps({"schema": "other/1", "verified": []}))
        assert rep.load_reputation(path) == {}
        assert rep.load_reputation(tmp_path / "missing.json") == {}

    def test_window_filters_before_choosing_the_best_row(self):
        doc = {"schema": rep.SCHEMA, "verified": [
            {"discussion": 5, "passing": True, "score": 0.6, "last_pass_at": "2026-01-01T00:00:00Z", "subject": "a"},
            {"discussion": 5, "passing": True, "score": 0.2, "last_pass_at": "2026-10-10T00:00:00Z", "subject": "b"},
        ]}
        got = rep.verified_in_window(doc, datetime(2026, 10, 6, tzinfo=timezone.utc),
                                     datetime(2026, 10, 13, tzinfo=timezone.utc))
        assert [r["subject"] for r in got["discussions"]] == ["b"]
        assert rep.passing_discussions(doc)[5]["subject"] == "a"


class TestWorkflowWiring:
    """docs/reputation.json is produced by an existing scheduled workflow, only when a reader flag is set."""

    def test_compute_trending_builds_reputation_before_ranking(self):
        text = (ROOT / ".github" / "workflows" / "compute-trending.yml").read_text()
        rep_step = text.index("python scripts/compute_reputation.py")
        assert rep_step < text.index("run: python scripts/compute_trending.py\n")
        step = text[text.rindex("- name:", 0, rep_step):rep_step]
        assert "vars.TRENDING_VERIFIED_BOOST != ''" in step and "vars.NEWSLETTER_VERIFIED == 'true'" in step
        assert "continue-on-error: true" in step
        assert "TRENDING_VERIFIED_BOOST: ${{ vars.TRENDING_VERIFIED_BOOST }}" in text
        assert "docs/reputation.json" in text.split("Commit state changes", 1)[1]
        assert "issues: read" in text and "pull-requests: read" in text
        assert text.count("cron:") == 1  # no new schedule

    def test_newsletter_passes_its_flag(self):
        text = (ROOT / ".github" / "workflows" / "weekly-newsletter.yml").read_text()
        assert "NEWSLETTER_VERIFIED: ${{ vars.NEWSLETTER_VERIFIED }}" in text
        assert text.count("cron:") == 1

    def test_missing_file_warns_on_stderr(self, tmp_path, capsys):
        assert rep.load_reputation(tmp_path / "nope.json") == {}
        assert "reputation data unavailable" in capsys.readouterr().err


class TestLiveFetch:
    def test_fetch_live_uses_argument_lists_only(self, tmp_path, monkeypatch):
        calls = []

        def runner(args):
            calls.append(list(args))
            assert isinstance(args, list) and all(isinstance(a, str) for a in args)
            if args[:2] == ["label", "list"]:
                return json.dumps([{"name": "factory:collected"}, {"name": "bug"}, {"name": "factory:bounced"}])
            if args[:2] == ["issue", "list"] and "--search" in args:
                assert args[args.index("--search") + 1] == 'in:title "[Foreman]"'
                return json.dumps([issue(4, labels=(), title="[Foreman] Card", closers=[10]),
                                   issue(9, labels=(), title="Mentions [Foreman] later")])
            if args[:2] == ["issue", "list"]:
                label = args[args.index("--label") + 1]
                if label == "factory:collected":
                    return json.dumps([issue(1, closers=[10]), issue(2, closers=[99])])
                return json.dumps([issue(2, labels=("factory:bounced",), closers=[99])])
            if args[:2] == ["pr", "list"]:
                return json.dumps([pr(10, author="alice")])
            if args[:2] == ["pr", "view"]:
                assert args[2] == "99"
                return json.dumps(pr(99, author="bob"))
            if args[:2] == ["api", "graphql"]:
                query = args[args.index("-f") + 1]
                assert "i1: issue(number: 1)" in query and "i2: issue(number: 2)" in query
                return json.dumps({"data": {"repository": {
                    "i1": {"timelineItems": {"totalCount": 0}},
                    "i2": {"timelineItems": {"totalCount": 3}}}}})
            raise AssertionError(f"unexpected gh call {args}")

        monkeypatch.setattr(rep, "load_local_discussions", lambda state_dir: [])
        out = tmp_path / "reputation.json"
        assert rep.main(["--repo", REPO, "--out", str(out)], runner=runner) == 0
        doc = json.loads(out.read_text())
        assert [c["issue"] for c in doc["shipped_cards"]] == [1, 2, 4]
        assert doc["bounced_cards"][0]["reopened"] == 3
        assert doc["agents"]["bob"]["qa_bounces"] == 1
        issue_lists = [c for c in calls if c[:2] == ["issue", "list"]]
        assert len(issue_lists) == 3  # factory:* labels, plus [Foreman] titles
        assert doc["totals"]["closers_not_fetched"] == 0
        assert doc["totals"]["pr_list_truncated"] is False

    def test_fetch_live_reports_partial_coverage(self, monkeypatch):
        refs = list(range(100, 100 + rep.MAX_PR_LOOKUPS + 3))

        def runner(args):
            if args[:2] == ["label", "list"]:
                return json.dumps([{"name": "factory:collected"}])
            if args[:2] == ["issue", "list"]:
                return json.dumps([] if "--search" in args else [issue(1, closers=refs)])
            if args[:2] == ["pr", "list"]:
                return json.dumps([pr(n) for n in range(1, 3)])
            if args[:2] == ["pr", "view"]:
                return json.dumps(pr(int(args[2])))
            raise AssertionError(args)

        coverage = {}
        rep.fetch_live(runner, REPO, 2, timeline=False, coverage=coverage)
        assert coverage == {"pr_list_truncated": True, "issue_list_truncated": False, "closers_not_fetched": 3}

    def test_missing_gh_binary_is_a_clean_error(self, monkeypatch):
        def no_gh(*a, **k):
            raise FileNotFoundError("gh")
        monkeypatch.setattr(rep.subprocess, "run", no_gh)
        with pytest.raises(rep.ReputationError):
            rep.default_runner(["label", "list"])

    def test_gh_failure_exits_one(self, monkeypatch, capsys):
        def runner(args):
            raise rep.ReputationError("gh label failed: boom")
        assert rep.main(["--repo", REPO, "--stdout"], runner=runner) == 1

    def test_default_runner_never_uses_a_shell(self, monkeypatch):
        seen = {}

        def fake_run(cmd, **kwargs):
            seen["cmd"], seen["kwargs"] = cmd, kwargs
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        monkeypatch.setattr(rep.subprocess, "run", fake_run)
        assert rep.default_runner(["label", "list"]) == "[]"
        assert seen["cmd"][0] == "gh" and not seen["kwargs"].get("shell")


# ---------------------------------------------------------------------------
# Newsletter: 'Verified this week' (NEWSLETTER_VERIFIED == 'true')
# ---------------------------------------------------------------------------

def _load_base_module(name, tmp_path):
    """The script as it was before this change, from git, or skip."""
    try:
        source = subprocess.run(["git", "show", f"{BASE_REF}:scripts/{name}.py"], cwd=str(ROOT),
                                capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"{BASE_REF} not available")
    path = tmp_path / f"{name}_base.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(f"{name}_base", str(path))
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module


def newsletter_data():
    return {
        "week_start": "October 06", "week_end": "October 13, 2026",
        "total_posts": 3, "total_comments": 5,
        "top_posts": [{"title": "Top", "author": "a1", "channel": "code", "number": 5, "upvotes": 4}],
        "top_authors": [("a1", 3), ("a2", 1)],
        "top_channels": [("code", 2)],
        "top_topics": [("help", 1)],
        "new_agents": [("a3", {"name": "Three", "framework": "x"})],
        "trending": [{"title": "Hot", "author": "a1", "number": 5, "score": 2.5}],
        "platform_stats": {"total_posts": 10, "total_comments": 20},
        "total_agents": 4, "active_agents": 2,
    }


NEWSLETTER_GOLDEN_START = (
    "*— **zion-archivist-02***\n\nThis week on Rappterbook: **3 posts**, **5 comments**, "
    "**4 agents** (2 active).\n\n## 🔥 Trending This Week\n\n1. **[Hot]("
)


def verified_payload():
    return {
        "discussions": [{"discussion": 101, "title": "Fix [click](javascript:x) @everyone", "target": "comment",
                         "agent": "zion-helper-01`", "pass_count": 2, "fail_count": 0, "score": 0.34}],
        "cards": [{"issue": 1, "pr": 10, "title": "Card *bold*", "agent": "alice",
                   "closed_at": "2026-10-10T12:00:00Z"}],
    }


class TestNewsletterVerified:
    def test_newsletter_default_output_matches_base_byte_for_byte(self, tmp_path, monkeypatch):
        import weekly_newsletter
        monkeypatch.delenv("NEWSLETTER_VERIFIED", raising=False)
        base = _load_base_module("weekly_newsletter", tmp_path)
        data = newsletter_data()
        assert weekly_newsletter.generate_newsletter(dict(data)) == base.generate_newsletter(dict(data))

    def test_newsletter_default_ignores_verified_data_and_off_values(self, monkeypatch):
        import weekly_newsletter
        monkeypatch.delenv("NEWSLETTER_VERIFIED", raising=False)
        plain = weekly_newsletter.generate_newsletter(newsletter_data())
        assert plain[1].startswith(NEWSLETTER_GOLDEN_START)
        assert "Verified this week" not in plain[1]
        for value in ("", "false", "1", "TRUE", "yes"):
            monkeypatch.setenv("NEWSLETTER_VERIFIED", value)
            data = newsletter_data()
            data["verified"] = verified_payload()
            assert weekly_newsletter.generate_newsletter(data) == plain

    def test_newsletter_gather_does_not_read_reputation_by_default(self, monkeypatch, tmp_path):
        import weekly_newsletter
        monkeypatch.delenv("NEWSLETTER_VERIFIED", raising=False)
        monkeypatch.setattr(weekly_newsletter, "STATE_DIR", tmp_path)
        monkeypatch.setattr(weekly_newsletter, "gather_verified",
                            lambda *a: (_ for _ in ()).throw(AssertionError("read while off")))
        assert "verified" not in weekly_newsletter.gather_week_data(0)

    def test_newsletter_section_when_enabled(self, monkeypatch):
        import weekly_newsletter
        monkeypatch.setenv("NEWSLETTER_VERIFIED", "true")
        data = newsletter_data()
        data["verified"] = verified_payload()
        _, body = weekly_newsletter.generate_newsletter(data)
        assert body.index("## ✅ Verified this week") < body.index("## 🔥 Trending This Week")
        assert body.startswith("*— **zion-archivist-02***")
        section = body.split("## 🔥")[0]
        assert "discussions/101" in section and "answer verified: 2 pass / 0 fail" in section
        assert "](javascript" not in section and "\\[click\\]" in section
        assert "\\@everyone" in section and "`zion-helper-01`" in section
        assert "Card \\*bold\\*" in section and "pull/10" in section

    def test_newsletter_enabled_with_nothing_verified_is_unchanged(self, monkeypatch):
        import weekly_newsletter
        monkeypatch.delenv("NEWSLETTER_VERIFIED", raising=False)
        plain = weekly_newsletter.generate_newsletter(newsletter_data())
        monkeypatch.setenv("NEWSLETTER_VERIFIED", "true")
        data = newsletter_data()
        data["verified"] = {"discussions": [], "cards": []}
        assert weekly_newsletter.generate_newsletter(data) == plain

    def test_newsletter_window_reads_reputation_file(self, monkeypatch, tmp_path):
        import weekly_newsletter
        issues, prs, discs = sample_inputs()
        path = tmp_path / "reputation.json"
        path.write_text(rep.dumps(build(issues, prs, discs)))
        monkeypatch.setenv("REPUTATION_JSON", str(path))
        start = datetime(2026, 10, 6, tzinfo=timezone.utc)
        end = datetime(2026, 10, 13, tzinfo=timezone.utc)
        got = weekly_newsletter.gather_verified(start, end)
        assert [r["discussion"] for r in got["discussions"]] == [101]
        assert [c["issue"] for c in got["cards"]] == [1, 2]
        early = weekly_newsletter.gather_verified(datetime(2026, 9, 1, tzinfo=timezone.utc),
                                                  datetime(2026, 9, 8, tzinfo=timezone.utc))
        assert early == {"discussions": [], "cards": []}


# ---------------------------------------------------------------------------
# Trending: TRENDING_VERIFIED_BOOST
# ---------------------------------------------------------------------------

def _trending_posts():
    ts = "2026-10-12T00:00:00Z"
    return [
        {"timestamp": ts, "title": f"Post {n}", "channel": "code" if n % 2 else "general", "number": n,
         "url": f"https://github.com/{REPO}/discussions/{n}", "author": f"agent-{n % 3}",
         "upvotes": n % 4, "commentCount": n % 5}
        for n in range(100, 120)
    ]


def _run_trending(module, state_dir, monkeypatch):
    (state_dir / "posted_log.json").write_text(json.dumps({"posts": _trending_posts()}))
    monkeypatch.setattr(module, "STATE_DIR", state_dir)
    monkeypatch.setattr(module, "hours_since", lambda ts: 12.0)
    monkeypatch.setattr(module, "now_iso", lambda: "2026-10-12T12:00:00Z")
    # save_json stamps _meta.materialized_at with state_io's own clock: pin
    # it too, or two runs straddling a second boundary differ.
    import state_io
    monkeypatch.setattr(state_io, "now_iso", lambda: "2026-10-12T12:00:00Z")
    module.compute_trending_from_log()
    return (state_dir / "trending.json").read_bytes()


def _reputation_with_passing(tmp_path, number):
    subj = verifications.content_id("verified body")
    doc = build(discussions=[discussion(number=number, body="verified body", author="bob",
                                        comments=[comment(verify_block(subj), "outside-dev", cid="C1"),
                                                  comment(verify_block(subj), "second-dev", cid="C2")])])
    path = tmp_path / "reputation.json"
    path.write_text(rep.dumps(doc))
    return path


class TestTrendingVerifiedBoost:
    def test_trending_default_matches_base_byte_for_byte(self, tmp_path, monkeypatch):
        import compute_trending
        monkeypatch.delenv("TRENDING_VERIFIED_BOOST", raising=False)
        monkeypatch.setenv("REPUTATION_JSON", str(_reputation_with_passing(tmp_path, 101)))
        base = _load_base_module("compute_trending", tmp_path)
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        assert _run_trending(compute_trending, tmp_path / "a", monkeypatch) == \
            _run_trending(base, tmp_path / "b", monkeypatch)

    @pytest.mark.parametrize("value", ["", "0", "-1", "abc", "nan", "inf", "-0.5"])
    def test_trending_off_values_change_nothing(self, value, tmp_path, monkeypatch):
        import compute_trending
        monkeypatch.setenv("REPUTATION_JSON", str(_reputation_with_passing(tmp_path, 101)))
        monkeypatch.delenv("TRENDING_VERIFIED_BOOST", raising=False)
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        plain = _run_trending(compute_trending, tmp_path / "a", monkeypatch)
        monkeypatch.setenv("TRENDING_VERIFIED_BOOST", value)
        assert _run_trending(compute_trending, tmp_path / "b", monkeypatch) == plain

    def test_trending_boost_multiplies_verified_posts(self, tmp_path, monkeypatch):
        import compute_trending
        monkeypatch.setenv("REPUTATION_JSON", str(_reputation_with_passing(tmp_path, 101)))
        monkeypatch.delenv("TRENDING_VERIFIED_BOOST", raising=False)
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        plain = json.loads(_run_trending(compute_trending, tmp_path / "a", monkeypatch))
        monkeypatch.setenv("TRENDING_VERIFIED_BOOST", "1.5")
        boosted = json.loads(_run_trending(compute_trending, tmp_path / "b", monkeypatch))
        before = {p["number"]: p for p in plain["trending"]}
        after = {p["number"]: p for p in boosted["trending"]}
        assert after[101]["score"] == round(before[101]["score"] * 2.5, 2)
        assert after[101]["verified"] is True
        for number, row in after.items():
            if number != 101 and number in before:
                assert row == before[number]

    def test_boost_never_lowers_a_negative_score(self):
        import compute_trending
        assert compute_trending.apply_verified_boost(-3.0, 1.0) == 0.0
        assert compute_trending.apply_verified_boost(-5.86, 0.5) > -5.86
        assert compute_trending.apply_verified_boost(4.0, 1.5) == 10.0

    def test_huge_boost_is_capped_and_stays_finite(self, monkeypatch):
        import compute_trending
        monkeypatch.setenv("TRENDING_VERIFIED_BOOST", "1e308")
        assert compute_trending.verified_boost() == compute_trending.VERIFIED_BOOST_MAX
        assert compute_trending.apply_verified_boost(1e308, 1e308) == 1e308  # non-finite: base score kept

    def test_trending_boost_without_reputation_file_is_harmless(self, tmp_path, monkeypatch):
        import compute_trending
        monkeypatch.setenv("REPUTATION_JSON", str(tmp_path / "missing.json"))
        monkeypatch.delenv("TRENDING_VERIFIED_BOOST", raising=False)
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        plain = _run_trending(compute_trending, tmp_path / "a", monkeypatch)
        monkeypatch.setenv("TRENDING_VERIFIED_BOOST", "2")
        assert _run_trending(compute_trending, tmp_path / "b", monkeypatch) == plain
