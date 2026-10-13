"""rapp-verification/1 library: scoring, one-live-vote, self-verify, parsing."""
from __future__ import annotations

import json

import pytest

import verifications as v

SUBJECT = v.content_id("def fix():\n    return 42\n")


def _rec(verifier="alice", passed=True, notes="ran it", **extra):
    base = {
        "verifier": verifier,
        "subject": SUBJECT,
        "subject_kind": "post",
        "environment": "python-3.11/macos-15",
        "passed": passed,
        "notes": notes,
        "at": "2026-10-12T10:00:00Z",
    }
    base.update(extra)
    return base


def _store_with(pass_n, fail_n):
    store = v.load(None)
    for i in range(pass_n):
        v.record(store, _rec(verifier=f"p{i}", passed=True))
    for i in range(fail_n):
        v.record(store, _rec(verifier=f"f{i}", passed=False, notes="OperationalError"))
    return store


# ---------------------------------------------------------------------------
# content_id
# ---------------------------------------------------------------------------

def test_content_id_is_sha256_prefixed_and_line_ending_stable():
    assert SUBJECT.startswith("sha256:") and len(SUBJECT) == 7 + 64
    assert v.content_id("a\r\nb\n") == v.content_id("a\nb")
    assert v.content_id("a") != v.content_id("b")
    with pytest.raises(ValueError):
        v.content_id(b"bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# score: Wilson lower bound, hand-computed
# ---------------------------------------------------------------------------

def test_wilson_lower_bound_matches_hand_computed_values():
    # 8 pass / 2 fail: p=0.8, n=10, z=1.959964
    #   (0.8 + 0.192073 - 1.959964*sqrt(0.016 + 0.0096036)) / 1.384146 = 0.490162
    s = v.score(_store_with(8, 2), SUBJECT)
    assert s["pass_count"] == 8 and s["fail_count"] == 2 and s["votes"] == 10
    assert s["score"] == pytest.approx(0.490162, abs=1e-5)
    assert s["hidden"] is False

    # 1 pass / 0 fail: p=1, n=1
    #   (1 + 1.920729 - 1.920729) / 4.841459 = 0.206549
    s1 = v.score(_store_with(1, 0), SUBJECT)
    assert s1["score"] == pytest.approx(0.206549, abs=1e-5)

    # More evidence at the same pass rate scores higher (that is the point).
    assert v.score(_store_with(80, 20), SUBJECT)["score"] > s["score"]


def test_score_with_no_votes_is_zero_and_not_hidden():
    store = v.load(None)
    assert v.score(store, SUBJECT) == {
        "pass_count": 0, "fail_count": 0, "votes": 0, "score": 0.0, "hidden": False,
    }
    assert v.is_hidden(store, SUBJECT) is False
    with pytest.raises(ValueError, match="load\\(\\)"):
        v.score({}, SUBJECT)  # a bare dict is not a store: fail closed, never "0 votes"


def test_all_fail_scores_zero():
    assert v.score(_store_with(0, 5), SUBJECT)["score"] == 0.0


# ---------------------------------------------------------------------------
# rules: one live vote, no self-verify, notes on fail, hide threshold
# ---------------------------------------------------------------------------

def test_revote_replaces_earlier_vote_by_same_login():
    store = v.load(None)
    v.record(store, _rec(verifier="alice", passed=True))
    v.record(store, _rec(verifier="Alice", passed=False, notes="broke on 3.9",
                         at="2026-10-12T11:00:00Z"))
    s = v.score(store, SUBJECT)
    assert s["votes"] == 1 and s["pass_count"] == 0 and s["fail_count"] == 1
    stored = store["subjects"][SUBJECT]["alice"]
    assert stored["notes"] == "broke on 3.9" and stored["at"] == "2026-10-12T11:00:00Z"


def test_self_verify_is_rejected_case_insensitively():
    store = v.load(None)
    with pytest.raises(ValueError, match="self-verification"):
        v.record(store, _rec(verifier="alice"), subject_owner="ALICE")
    assert v.score(store, SUBJECT)["votes"] == 0
    # unknown owner does not block
    v.record(store, _rec(verifier="alice"), subject_owner=None)
    v.record(store, _rec(verifier="bob"), subject_owner="alice")
    assert v.score(store, SUBJECT)["votes"] == 2


def test_notes_required_when_failed():
    store = v.load(None)
    with pytest.raises(ValueError, match="notes are required"):
        v.record(store, _rec(passed=False, notes=""))
    with pytest.raises(ValueError, match="notes are required"):
        v.record(store, _rec(passed=False, notes="   \n"))
    v.record(store, _rec(passed=True, notes=""))  # pass needs no notes
    assert v.score(store, SUBJECT)["pass_count"] == 1


def test_hide_threshold_is_five_votes_and_under_twenty_percent():
    assert v.is_hidden(_store_with(0, 4), SUBJECT) is False   # too few votes
    assert v.is_hidden(_store_with(0, 5), SUBJECT) is True    # 0/5
    assert v.is_hidden(_store_with(1, 5), SUBJECT) is True    # 1/6 = 16.7%
    assert v.is_hidden(_store_with(1, 4), SUBJECT) is False   # exactly 20% is not hidden
    assert v.is_hidden(_store_with(4, 1), SUBJECT) is False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"verifier": "-bad-"},
    {"verifier": "a" * 40},
    {"subject": "sha256:XYZ"},
    {"subject": "discussion:123"},
    {"subject_kind": "comment"},
    {"passed": 1},
    {"passed": "true"},
    {"environment": ""},
    {"environment": "x" * 101},
    {"notes": "n" * 1001},
    {"at": "yesterday"},
    {"schema": "rapp-verification/2"},
])
def test_record_rejects_invalid_fields(bad):
    store = v.load(None)
    with pytest.raises(ValueError):
        v.record(store, _rec(**bad))
    assert store["subjects"] == {}


def test_record_normalizes_and_drops_unknown_keys():
    store = v.load(None)
    out = v.record(store, _rec(environment="  python-3.11 \n macos ", at="2026-10-12T12:00:00+02:00",
                               extra="ignored"))
    assert out["environment"] == "python-3.11 macos"
    assert out["at"] == "2026-10-12T10:00:00Z"
    assert "extra" not in out and out["schema"] == v.SCHEMA
    assert set(out) == {"schema", "verifier", "subject", "subject_kind",
                        "environment", "passed", "notes", "at"}


def test_record_fills_at_when_missing():
    store = v.load(None)
    rec = _rec()
    del rec["at"]
    assert v.record(store, rec)["at"].endswith("Z")


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------

def test_load_missing_returns_empty_and_roundtrips(tmp_path):
    path = tmp_path / "nested" / "verifications.json"
    store = v.load(path)
    assert store == {"schema": v.SCHEMA, "subjects": {}}
    v.record(store, _rec())
    v.save(store, path)
    again = v.load(path)
    assert again == store
    assert json.loads(path.read_text())["schema"] == v.SCHEMA
    assert not list(tmp_path.glob("**/*.tmp"))


def test_load_fails_closed_on_foreign_or_corrupt_file(tmp_path):
    corrupt = tmp_path / "c.json"
    corrupt.write_text("{not json")
    with pytest.raises(ValueError):
        v.load(corrupt)
    foreign = tmp_path / "f.json"
    foreign.write_text(json.dumps({"schema": "other/1", "subjects": {}}))
    with pytest.raises(ValueError):
        v.load(foreign)
    with pytest.raises(ValueError):
        v.save({"schema": "other/1", "subjects": {}}, tmp_path / "x.json")


# ---------------------------------------------------------------------------
# parse_comment
# ---------------------------------------------------------------------------

HAPPY = (
    "Reproduced on a clean venv.\n\n"
    "```json\n"
    + json.dumps({
        "action": "verify",
        "subject": SUBJECT,
        "subject_kind": "post",
        "environment": "python-3.11/macos-15",
        "passed": True,
        "notes": "fixed the OperationalError",
    })
    + "\n```\n\nThanks!"
)


def test_parse_comment_happy_path_then_record():
    rec = v.parse_comment(HAPPY)
    assert rec == {
        "schema": v.SCHEMA,
        "subject": SUBJECT,
        "subject_kind": "post",
        "environment": "python-3.11/macos-15",
        "passed": True,
        "notes": "fixed the OperationalError",
    }
    # identity comes from the transport, never the body
    rec["verifier"] = "carol"
    rec["at"] = "2026-10-12T09:00:00Z"
    store = v.load(None)
    v.record(store, rec, subject_owner="alice")
    assert v.score(store, SUBJECT)["pass_count"] == 1


def test_parse_comment_accepts_verdict_alias_and_bare_fence():
    body = "```\n" + json.dumps({
        "action": "verify", "subject": SUBJECT, "verdict": "fail",
        "environment": "node-20", "notes": "TypeError at line 3",
    }) + "\n```"
    rec = v.parse_comment(body)
    assert rec is not None and rec["passed"] is False and rec["subject_kind"] == "post"


def test_parse_comment_ignores_verifier_claimed_in_body():
    body = "```json\n" + json.dumps({
        "action": "verify", "subject": SUBJECT, "environment": "py", "passed": True,
        "verifier": "kody-w", "at": "1999-01-01T00:00:00Z",
    }) + "\n```"
    rec = v.parse_comment(body)
    assert rec is not None and "verifier" not in rec and "at" not in rec


@pytest.mark.parametrize("body", [
    # 1. plain prose, no fence
    '{"action": "verify", "subject": "' + SUBJECT + '", "environment": "py", "passed": true}',
    # 2. fenced but not JSON
    "```json\n{action: verify, passed: yes}\n```",
    # 3. valid JSON but wrong action
    "```json\n" + json.dumps({"action": "vote", "subject": SUBJECT, "passed": True}) + "\n```",
    # 4. passed is a string, not a boolean
    "```json\n" + json.dumps({"action": "verify", "subject": SUBJECT,
                               "environment": "py", "passed": "true"}) + "\n```",
    # 5. fail without notes
    "```json\n" + json.dumps({"action": "verify", "subject": SUBJECT,
                               "environment": "py", "passed": False}) + "\n```",
    # 6. passed and verdict disagree
    "```json\n" + json.dumps({"action": "verify", "subject": SUBJECT, "environment": "py",
                               "passed": True, "verdict": "fail", "notes": "x"}) + "\n```",
    # 7. duplicate keys
    "```json\n{\"action\": \"verify\", \"subject\": \"" + SUBJECT
    + "\", \"environment\": \"py\", \"passed\": false, \"passed\": true}\n```",
    # 8. two verify blocks
    HAPPY + "\n" + HAPPY,
    # 9. top-level array
    "```json\n[" + json.dumps({"action": "verify", "subject": SUBJECT,
                                "environment": "py", "passed": True}) + "]\n```",
    # 10. oversized body
    HAPPY + ("x" * v.MAX_COMMENT_BODY),
    # 11. not a string
    None,
])
def test_parse_comment_rejects_malformed(body):
    assert v.parse_comment(body) is None


def test_parse_comment_finds_verify_block_after_other_code_blocks():
    body = (
        "Here is what I ran:\n\n```python\nprint('hi')\n```\n\nResult:\n\n" + HAPPY
    )
    rec = v.parse_comment(body)
    assert rec is not None and rec["passed"] is True
    # a verify object inside a non-json block is not a vote
    inside_python = "```python\n" + json.dumps({
        "action": "verify", "subject": SUBJECT, "environment": "py", "passed": True,
    }) + "\n```"
    assert v.parse_comment(inside_python) is None
    # an unterminated fence is not a block
    assert v.parse_comment(HAPPY.rsplit("```", 1)[0]) is None
    # CRLF bodies and four-backtick fences both work
    assert v.parse_comment(HAPPY.replace("\n", "\r\n")) is not None
    assert v.parse_comment(HAPPY.replace("```json", "````json").replace("\n```\n", "\n````\n")) is not None


def test_text_fields_drop_format_characters_and_normalize():
    store = v.load(None)
    out = v.record(store, _rec(environment="py\u200bthon-3.11\u202e", notes="ok\ufeff\u2066!\u2069"))
    assert out["environment"] == "python-3.11"
    assert out["notes"] == "ok!"
    # meaningful format characters stay: ZWJ in emoji sequences and identifiers, ZWNJ in Persian
    kept = v.record(store, _rec(verifier="zw", notes="ReferenceError: a\u200db is not defined \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"))
    assert kept["notes"] == "ReferenceError: a\u200db is not defined \u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645"
    # NFC: decomposed e + combining acute equals precomposed e-acute
    a = v.record(store, _rec(verifier="x1", environment="café"))
    b = v.record(store, _rec(verifier="x2", environment="café"))
    assert a["environment"] == b["environment"]


def test_hide_boundary_uses_integer_arithmetic():
    assert v.is_hidden(_store_with(3, 12), SUBJECT) is False   # 3/15 == 0.20 exactly
    assert v.is_hidden(_store_with(3, 13), SUBJECT) is True    # 3/16 < 0.20


def test_load_rejects_tampered_records(tmp_path):
    path = tmp_path / "v.json"
    path.write_text(json.dumps({
        "schema": v.SCHEMA,
        "subjects": {SUBJECT: {"mallory": {"passed": True}}},
    }))
    with pytest.raises(ValueError, match="corrupt"):
        v.load(path)
    path.write_text(json.dumps({"schema": v.SCHEMA, "subjects": {SUBJECT: ["x"]}}))
    with pytest.raises(ValueError, match="corrupt"):
        v.load(path)
    # key/verifier mismatch is also refused
    rec = _rec(verifier="alice")
    rec["schema"] = v.SCHEMA
    path.write_text(json.dumps({"schema": v.SCHEMA, "subjects": {SUBJECT: {"bob": rec}}}))
    with pytest.raises(ValueError, match="key mismatch"):
        v.load(path)


def test_score_raises_on_poisoned_store():
    with pytest.raises(ValueError):
        v.score({"schema": v.SCHEMA, "subjects": {SUBJECT: ["not", "a", "dict"]}}, SUBJECT)
    with pytest.raises(ValueError):
        v.score({"schema": v.SCHEMA, "subjects": {SUBJECT: {"a": "str"}}}, SUBJECT)


# ---------------------------------------------------------------------------
# findings from the adversarial Copilot (gpt-6.1-sol) pass, each pinned
# ---------------------------------------------------------------------------

def _verify_body(**fields):
    obj = {"action": "verify", "subject": SUBJECT, "environment": "py", "passed": True}
    obj.update(fields)
    return "```json\n" + json.dumps(obj) + "\n```"


def test_deeply_nested_json_is_malformed_not_a_crash():
    obj = {"action": "verify", "subject": SUBJECT, "environment": "py", "passed": True}
    inner = json.dumps(obj)[:-1] + ',"extra":' + "[" * 1100 + "0" + "]" * 1100 + "}"
    # Python <= 3.11 raises RecursionError here and 3.12+ parses it happily; the
    # library's own MAX_JSON_DEPTH cap must reject it on every interpreter.
    with pytest.raises(ValueError, match="nested too deeply"):
        v._loads_strict(inner)
    body = "```json\n" + inner + "\n```"
    assert len(body) < v.MAX_COMMENT_BODY
    assert v.parse_comment(body) is None


def test_json_depth_cap_is_exact_and_ignores_brackets_inside_strings():
    at_cap = "[" * v.MAX_JSON_DEPTH + "0" + "]" * v.MAX_JSON_DEPTH
    assert v._loads_strict(at_cap) is not None
    with pytest.raises(ValueError, match="nested too deeply"):
        v._loads_strict("[" + at_cap + "]")
    assert v._loads_strict('{"notes": "[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[ ]"}') == {"notes": "[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[ ]"}
    assert v._loads_strict('{"notes": "a \\" [ b"}') == {"notes": 'a " [ b'}


def test_lone_surrogates_are_rejected_before_they_can_poison_save(tmp_path):
    assert v.parse_comment(_verify_body(notes="\ud800")) is None
    store = v.load(None)
    with pytest.raises(ValueError, match="surrogate"):
        v.record(store, _rec(environment="py\ud800"))
    assert store["subjects"] == {}


def test_content_id_normalizes_line_endings_and_final_newlines_only():
    assert v.content_id("print(42)") != v.content_id("    print(42)")
    assert v.content_id("# heading") != v.content_id("    # heading")
    assert v.content_id("body\n\n") == v.content_id("body") == v.content_id("body\r\n")
    # anything that can change what executable text does is a different subject
    assert v.content_id("body   \n") != v.content_id("body")          # trailing space on a line
    assert v.content_id("\nbody") != v.content_id("body")             # leading blank line (shebang moves)
    heredoc = "cat <<'EOF'\nSAFE\nEOF\nrm -rf /\nEOF"
    assert v.content_id(heredoc) != v.content_id(heredoc.replace("\nEOF\nrm", "\nEOF \nrm"))


def test_older_vote_does_not_overwrite_newer_vote():
    store = v.load(None)
    newer = v.record(store, _rec(verifier="carol", passed=False, notes="broke",
                                 at="2026-10-12T12:00:00Z"))
    returned = v.record(store, _rec(verifier="carol", passed=True,
                                    at="2026-01-01T12:00:00Z"))
    assert returned == newer
    assert v.score(store, SUBJECT) == {
        "pass_count": 0, "fail_count": 1, "votes": 1, "score": 0.0, "hidden": False,
    }
    # equal timestamp: last write wins
    v.record(store, _rec(verifier="carol", passed=True, at="2026-10-12T12:00:00Z"))
    assert v.score(store, SUBJECT)["pass_count"] == 1


def test_example_inside_tilde_fence_is_not_a_vote_but_tilde_json_block_is():
    inner = _verify_body()
    assert v.parse_comment("~~~~markdown\n" + inner + "\n~~~~") is None
    assert v.parse_comment("````markdown\n" + inner + "\n````") is None
    tilde_json = "~~~json\n" + json.dumps({
        "action": "verify", "subject": SUBJECT, "environment": "py", "passed": True,
    }) + "\n~~~"
    assert v.parse_comment(tilde_json) is not None
    # a tab-indented ``` line is content, not a closing fence
    body = "```python\n\t```\n" + json.dumps({"action": "verify", "subject": SUBJECT,
                                              "environment": "py", "passed": True}) + "\n```"
    assert v.parse_comment(body) is None
    # mismatched fence characters do not close each other
    assert v.parse_comment("~~~\n" + inner + "\n```") is None


def test_score_and_save_reject_dict_shaped_junk(tmp_path):
    poisoned = {"schema": v.SCHEMA, "subjects": {SUBJECT: {str(i): {} for i in range(5)}}}
    with pytest.raises(ValueError, match="corrupt"):
        v.score(poisoned, SUBJECT)
    with pytest.raises(ValueError, match="refusing to save"):
        v.save(poisoned, tmp_path / "p.json")
    assert not (tmp_path / "p.json").exists() and not list(tmp_path.glob("*.tmp"))
    # a vote whose stored subject disagrees with its bucket is refused too
    rec = _rec(verifier="alice")
    rec["schema"] = v.SCHEMA
    other = v.content_id("other")
    with pytest.raises(ValueError, match="key mismatch"):
        v.save({"schema": v.SCHEMA, "subjects": {other: {"alice": rec}}}, tmp_path / "q.json")


def test_load_rejects_duplicate_keys_in_ledger(tmp_path):
    store = v.load(None)
    v.record(store, _rec())
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(store)[:-1] + ',"subjects":{}}')
    with pytest.raises(ValueError, match="duplicate key"):
        v.load(path)


def test_trailing_newline_does_not_pass_canonical_validators():
    store = v.load(None)
    with pytest.raises(ValueError, match="verifier"):
        v.record(store, _rec(verifier="alice\n"), subject_owner="alice")
    with pytest.raises(ValueError, match="subject"):
        v.record(store, _rec(subject=SUBJECT + "\n"))
    assert v.parse_comment(_verify_body(subject=SUBJECT + "\n")) is None


@pytest.mark.parametrize("at", [
    "0001-01-01T00:00:00+01:00",
    "9999-12-31T23:59:59-01:00",
    "2026-10-12T23:59:60Z",
])
def test_extreme_timestamps_are_value_errors(at):
    with pytest.raises(ValueError, match="at must be"):
        v.record(v.load(None), _rec(at=at))


def test_rfc_worked_values_are_pinned():
    assert v.score(_store_with(80, 20), SUBJECT)["score"] == pytest.approx(0.711171, abs=1e-6)
    assert v.score(_store_with(1, 0), SUBJECT)["score"] == pytest.approx(0.206549, abs=1e-6)
    assert v.score(_store_with(8, 2), SUBJECT)["score"] == pytest.approx(0.490162, abs=1e-6)


def test_fractional_second_ordering_is_by_instant_not_text():
    store = v.load(None)
    v.record(store, _rec(verifier="dan", passed=True, at="2026-10-12T12:00:00.500000Z"))
    out = v.record(store, _rec(verifier="dan", passed=False, notes="older",
                               at="2026-10-12T12:00:00Z"))
    assert out["passed"] is True and out["at"] == "2026-10-12T12:00:00.500000Z"
    store2 = v.load(None)
    v.record(store2, _rec(verifier="dan", passed=True, at="2026-10-12T12:00:00Z"))
    v.record(store2, _rec(verifier="dan", passed=False, notes="newer",
                          at="2026-10-12T12:00:00.500000Z"))
    assert v.score(store2, SUBJECT)["fail_count"] == 1


def test_only_value_error_escapes_on_bad_shapes(tmp_path):
    bucket_is_list = {"schema": v.SCHEMA, "subjects": {SUBJECT: []}}
    with pytest.raises(ValueError):
        v.record(bucket_is_list, _rec())
    with pytest.raises(ValueError):
        v.score(bucket_is_list, SUBJECT)          # not silently zero votes
    with pytest.raises(ValueError):
        v.score(v.load(None), [])                 # unhashable subject
    with pytest.raises(ValueError):
        v.score(v.load(None), None)
    with pytest.raises(ValueError):
        v.load(123)
    with pytest.raises(ValueError):
        v.save(v.load(None), 123)
    partial = {"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": {"passed": True}}}}
    with pytest.raises(ValueError):
        v.score(partial, SUBJECT)                 # partial record is not a vote
    with pytest.raises(ValueError):
        v.record(partial, _rec(verifier="alice"))  # nor can it be built on
    assert not list(tmp_path.iterdir())


def test_public_surface_is_exactly_the_contract():
    assert set(v.__all__) == {
        "content_id", "load", "record", "score", "is_hidden", "save", "parse_comment",
    }


# ---------------------------------------------------------------------------
# findings from the second adversarial pass (fixer round), each pinned
# ---------------------------------------------------------------------------

def test_non_string_subject_owner_is_an_error_not_an_unknown_owner():
    store = v.load(None)
    for bad in (b"alice", {"alice": 1}, 7, object(), [None], [""], " "):
        with pytest.raises(ValueError, match="subject_owner"):
            v.record(store, _rec(verifier="alice"), subject_owner=bad)
    assert store["subjects"] == {}


def test_subject_owner_accepts_several_owners_and_rejects_any_of_them():
    store = v.load(None)
    with pytest.raises(ValueError, match="self-verification"):
        v.record(store, _rec(verifier="alice"), subject_owner=["zion-coder-01", "ALICE "])
    with pytest.raises(ValueError, match="self-verification"):
        v.record(store, _rec(verifier="zion-coder-01"), subject_owner=("alice", "zion-coder-01"))
    v.record(store, _rec(verifier="bob"), subject_owner=["alice", "zion-coder-01"])
    assert v.score(store, SUBJECT)["votes"] == 1


def test_timestamp_grammar_is_fixed_by_the_library_not_the_interpreter():
    store = v.load(None)
    out = v.record(store, _rec(verifier="a1", at="2026-10-12T12:00:00.5Z"))
    assert out["at"] == "2026-10-12T12:00:00.500000Z"
    assert v.record(store, _rec(verifier="a2", at="2026-10-12T12:00:00.1Z"))["at"] == "2026-10-12T12:00:00.100000Z"
    assert v.record(store, _rec(verifier="a3", at="2026-10-12T12:00:00.000000Z"))["at"] == "2026-10-12T12:00:00Z"
    assert v.record(store, _rec(verifier="a4", at="2026-10-12T14:00:00+02:00"))["at"] == "2026-10-12T12:00:00Z"
    for bad in ("20261012T120000Z", "2026-10-12 12:00:00Z", "2026-10-12T12:00:00.1234567Z",
                "2026-10-12T12:00:00", "2026-10-12T12:00:00+0200", "2026-10-12", "2026-10-12T12:00Z",
                "2026-10-12T12:00:00Z\n", 1760270400):
        with pytest.raises(ValueError, match="at must be"):
            v.record(store, _rec(verifier="a5", at=bad))


def test_persisted_vote_without_at_is_corrupt_not_redated(tmp_path):
    rec = _rec(verifier="alice")
    del rec["at"]
    rec["schema"] = v.SCHEMA
    path = tmp_path / "v.json"
    path.write_text(json.dumps({"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec}}}))
    with pytest.raises(ValueError, match="at is required"):
        v.load(path)
    rec["at"] = None
    path.write_text(json.dumps({"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec}}}))
    with pytest.raises(ValueError, match="at is required"):
        v.load(path)
    with pytest.raises(ValueError):
        v.score({"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec}}}, SUBJECT)
    # fresh ingestion through record() may still default it
    fresh = _rec()
    del fresh["at"]
    assert v.record(v.load(None), fresh)["at"].endswith("Z")


def test_record_and_score_reject_stores_that_load_would_reject():
    foreign = {"schema": "foreign/1", "subjects": {}}
    with pytest.raises(ValueError):
        v.record(foreign, _rec())
    assert foreign == {"schema": "foreign/1", "subjects": {}}
    for junk in (None, [], "junk", {}, {"subjects": {}}, {"schema": v.SCHEMA}, {"schema": v.SCHEMA, "subjects": []}):
        with pytest.raises(ValueError):
            v.score(junk, SUBJECT)
        with pytest.raises(ValueError):
            v.record(junk, _rec())
    store = v.load(None)
    for bad_subject in ("not-an-id", "SHA256:" + "a" * 64, SUBJECT + " ", "", None, 3):
        with pytest.raises(ValueError, match="subject"):
            v.score(store, bad_subject)


def test_none_buckets_and_none_votes_are_corrupt_not_absent():
    with pytest.raises(ValueError, match="corrupt"):
        v.score({"schema": v.SCHEMA, "subjects": {SUBJECT: None}}, SUBJECT)
    with pytest.raises(ValueError, match="corrupt"):
        v.score({"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": None}}}, SUBJECT)
    poisoned = {"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": None}}}
    with pytest.raises(ValueError, match="corrupt"):
        v.record(poisoned, _rec(verifier="alice"))
    assert poisoned["subjects"][SUBJECT] == {"alice": None}
    with pytest.raises(ValueError, match="corrupt"):
        v.record({"schema": v.SCHEMA, "subjects": {SUBJECT: None}}, _rec(verifier="bob"))


def test_html_blocks_are_not_scanned_for_votes():
    inner = _verify_body()
    assert v.parse_comment("<!--\n" + inner + "\n-->") is None
    assert v.parse_comment("<!-- hidden -->\n" + inner) is not None   # one-line comment ends on its line
    assert v.parse_comment("<pre>\n" + inner + "\n</pre>") is None
    assert v.parse_comment("<PRE class=x>\n" + inner + "\n</PRE>\n") is None
    assert v.parse_comment("<script>\n" + inner + "\n</script>") is None
    assert v.parse_comment("<textarea>\n" + inner + "\n</textarea>") is None
    # CommonMark types 3-5: processing instruction, declaration, CDATA
    assert v.parse_comment("<?php\n" + inner + "\n?>") is None
    assert v.parse_comment("<!DOCTYPE\n" + inner + "\n>") is None
    assert v.parse_comment("<![CDATA[\n" + inner + "\n]]>") is None
    # types 6/7: any tag at line start opens a block that runs to the next blank line,
    # so a fence directly inside <div>, <details> or an unknown tag is raw HTML, not code
    assert v.parse_comment("<div><!--\n" + inner + "\n--></div>") is None
    assert v.parse_comment("<details>\n" + inner + "\n</details>") is None
    assert v.parse_comment("<prefix>\n" + inner + "\n</prefix>") is None
    assert v.parse_comment("</p>\n" + inner) is None
    # after the blank line that ends such a block, a fence is a code block again (as GitHub renders it)
    assert v.parse_comment("<details>\n<summary>run</summary>\n\n" + inner + "\n\n</details>") is not None
    # an unterminated comment swallows the rest of the comment
    assert v.parse_comment("<!--\n" + inner) is None
    # a block after the comment closes is visible again
    assert v.parse_comment("<!--\nnope\n-->\n" + inner) is not None
    # not tags: a bare '<' or '<3' starts no block
    assert v.parse_comment("< not a tag\n" + inner) is not None
    assert v.parse_comment("<3\n" + inner) is not None
    # a fence indented inside a list item is rendered by GitHub and counts
    assert v.parse_comment("- ran it:\n  " + inner.replace("\n", "\n  ")) is not None


def test_tilde_fence_info_string_may_contain_backticks():
    verify_json = json.dumps({"action": "verify", "subject": SUBJECT, "environment": "py", "passed": True})
    assert v.parse_comment("~~~`python`\n" + verify_json + "\n~~~") is None
    assert v.parse_comment("~~~ json extra words\n" + verify_json + "\n~~~") is not None
    assert v.parse_comment("```json extra words\n" + verify_json + "\n```") is not None
    assert v.parse_comment("``` json`x\n" + verify_json + "\n```") is None  # not a fence at all


def test_closing_fence_trims_only_ascii_whitespace():
    verify_json = json.dumps({"action": "verify", "subject": SUBJECT, "environment": "py", "passed": True})
    # "``` " is content, so the block stays open and nothing is a vote
    assert v.parse_comment("```python\n``` \n```json\n" + verify_json + "\n```") is None
    assert v.parse_comment("```json\n" + verify_json + "\n```\t \n") is not None


def test_content_id_touches_only_newlines():
    assert v.content_id("x=1") != v.content_id("x=1\u00a0")
    assert v.content_id("x=1") != v.content_id("x=1 \t\n")
    assert v.content_id("x=1") == v.content_id("x=1\n\n\n")
    assert v.content_id("\u00a0\nx=1") != v.content_id("x=1")
    assert v.content_id(" \t\n\nx=1") != v.content_id("x=1")


def test_load_translates_every_path_failure_to_value_error(tmp_path):
    with pytest.raises(ValueError, match="unreadable"):
        v.load("\x00")
    with pytest.raises(ValueError, match="unreadable"):
        v.load(tmp_path / ("x" * 300))
    with pytest.raises(ValueError, match="unreadable"):
        v.load(tmp_path)  # a directory
    assert v.load(tmp_path / "missing" / "deeper.json") == {"schema": v.SCHEMA, "subjects": {}}


def test_strict_json_rejects_nan_and_null_verdict():
    assert v.parse_comment("```json\n" + '{"action": "verify", "subject": "' + SUBJECT
                           + '", "environment": "py", "passed": true, "score": NaN}' + "\n```") is None
    assert v.parse_comment(_verify_body(verdict=None)) is None
    assert v.parse_comment(_verify_body(verdict="PASS")) is None
    with pytest.raises(ValueError):
        v._loads_strict('{"a": Infinity}')


def test_c1_controls_are_stripped_from_text():
    store = v.load(None)
    out = v.record(store, _rec(notes="py\x85thon\x9b[31m red\x1b[0m\x7f", environment="py\x80 3.11"))
    assert out["notes"] == "python[31m red[0m"
    assert out["environment"] == "py 3.11"


def test_automation_logins_are_rejected_not_scored():
    store = v.load(None)
    for bot in ("github-actions[bot]", "dependabot[bot]", "github-actions "):
        with pytest.raises(ValueError, match="verifier"):
            v.record(store, _rec(verifier=bot))
    assert v.score(store, SUBJECT)["votes"] == 0


# ---------------------------------------------------------------------------
# findings from the fixer-round Copilot (gpt-6.1-sol) pass on the library
# ---------------------------------------------------------------------------

def test_subject_owner_entries_must_be_logins():
    store = v.load(None)
    for bad in ("alice\u200b", "alice,bob", "a lice", "github-actions[bot]", ["alice", "-x-"]):
        with pytest.raises(ValueError, match="subject_owner"):
            v.record(store, _rec(verifier="alice"), subject_owner=bad)
    assert store["subjects"] == {}
    v.record(store, _rec(verifier="alice"), subject_owner=" Bob ")
    assert v.score(store, SUBJECT)["votes"] == 1


def test_offset_fields_are_range_checked_and_z_is_uppercase():
    store = v.load(None)
    for bad in ("2026-10-12T12:00:00+00:60", "2026-10-12T12:00:00-00:60", "2026-10-12T12:00:00+01:99",
                "2026-10-12T12:00:00+24:00", "2026-10-12T12:00:00z"):
        with pytest.raises(ValueError, match="at must be"):
            v.record(store, _rec(at=bad))
    assert v.record(store, _rec(at="2026-10-12T12:00:00-00:00"))["at"] == "2026-10-12T12:00:00Z"
    assert v.record(store, _rec(verifier="b", at="2026-10-12T12:00:00+23:59"))["at"] == "2026-10-11T12:01:00Z"


def test_integer_parsing_is_bounded_by_the_library_not_the_interpreter():
    assert v._loads_strict('{"n": ' + "9" * 100 + "}")["n"] == int("9" * 100)
    with pytest.raises(ValueError, match="digits"):
        v._loads_strict('{"n": ' + "9" * 101 + "}")
    body = "```json\n" + json.dumps({"action": "verify", "subject": SUBJECT, "environment": "py",
                                      "passed": True})[:-1] + ', "extra": ' + "1" * 5000 + "}\n```"
    assert v.parse_comment(body) is None


def test_save_rejects_bad_paths_before_touching_the_filesystem(tmp_path):
    store = v.load(None)
    v.record(store, _rec())
    with pytest.raises(ValueError, match="not a filesystem path"):
        v.save(store, str(tmp_path / "never") + "/\x00")
    assert not (tmp_path / "never").exists()
    assert list(tmp_path.iterdir()) == []


def test_record_and_score_validate_the_whole_store_like_load(tmp_path):
    other = v.content_id("other")
    rec = _rec(verifier="alice")
    rec["schema"] = v.SCHEMA
    # a poisoned bucket for a *different* subject blocks scoring and recording this one
    store = {"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec}, "invalid": None}}
    with pytest.raises(ValueError, match="corrupt"):
        v.score(store, SUBJECT)
    with pytest.raises(ValueError, match="corrupt"):
        v.record(store, _rec(verifier="bob"))
    assert "bob" not in store["subjects"][SUBJECT]
    # a corrupt vote by another verifier in the same bucket blocks too
    store2 = {"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec, "bob": None}}}
    with pytest.raises(ValueError, match="corrupt"):
        v.record(store2, _rec(verifier="carol"))
    assert "carol" not in store2["subjects"][SUBJECT]
    # what load() accepts, score()/record() accept
    path = tmp_path / "ok.json"
    path.write_text(json.dumps({"schema": v.SCHEMA, "subjects": {SUBJECT: {"alice": rec}, other: {}}}))
    loaded = v.load(path)
    assert v.score(loaded, other)["votes"] == 0 and v.score(loaded, SUBJECT)["votes"] == 1
