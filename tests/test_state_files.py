"""`claims/<key>.toml` and `resources/<name>.toml` codecs: pure logic, no git subprocess."""

import pytest
from store_fixtures import CLAIM_BASE, TIP

from aco import protocol, state_files

_OTHER_TIP = protocol.ObjectId("b" * 40)


def _sample_claim(
    *,
    scope: tuple[str, ...] = ("src/aco/store.py",),
    resource: protocol.ResourceHold | None = None,
    whole_reason: str | None = None,
) -> protocol.ActiveClaim:
    return protocol.ActiveClaim(
        identity=protocol.IssueIdentity(42),
        claim_id=protocol.ClaimId("a1"),
        agent="Ada",
        role="builder",
        base=CLAIM_BASE,
        branch="claude/issue-42-cut",
        scope=scope,
        opened_commit=TIP,
        resource=resource,
        whole_reason=whole_reason,
    )


def test_serialize_and_parse_claim_toml_round_trips_the_minimal_claim() -> None:
    claim = _sample_claim()

    parsed = state_files.parse_claim_toml(
        state_files.serialize_claim_toml(claim), key="issue-42", tip=_OTHER_TIP
    )

    assert parsed == claim


def test_serialize_and_parse_claim_toml_round_trips_resource_and_whole_reason() -> None:
    claim = _sample_claim(
        resource=protocol.ResourceHold("display", 2), whole_reason="repo-wide rename"
    )

    parsed = state_files.parse_claim_toml(
        state_files.serialize_claim_toml(claim), key="issue-42", tip=_OTHER_TIP
    )

    assert parsed == claim


def test_serialize_and_parse_claim_toml_round_trips_a_quote_in_a_scope_path() -> None:
    claim = _sample_claim(scope=('weird "quoted" path.py',))

    parsed = state_files.parse_claim_toml(
        state_files.serialize_claim_toml(claim), key="issue-42", tip=_OTHER_TIP
    )

    assert parsed.scope == ('weird "quoted" path.py',)


def test_parse_claim_toml_rejects_an_unknown_key() -> None:
    content = state_files.serialize_claim_toml(_sample_claim()) + 'comment = "stray"\n'

    with pytest.raises(protocol.MalformedStateTreeError, match="unknown keys"):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_a_missing_required_key() -> None:
    with pytest.raises(protocol.MalformedStateTreeError, match="is missing"):
        state_files.parse_claim_toml('claim_id = "a1"\n', key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_resource_value_without_resource_name() -> None:
    content = state_files.serialize_claim_toml(_sample_claim()) + "resource_value = 3\n"

    with pytest.raises(protocol.MalformedStateTreeError, match="resource_value without"):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_a_malformed_commit_id() -> None:
    content = state_files.serialize_claim_toml(_sample_claim()).replace(
        str(CLAIM_BASE), "not-a-sha"
    )

    with pytest.raises(protocol.MalformedStateTreeError, match="malformed commit id"):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_malformed_toml() -> None:
    with pytest.raises(protocol.MalformedStateTreeError, match="malformed claim file"):
        state_files.parse_claim_toml("not = valid = toml\n", key="issue-42", tip=_OTHER_TIP)


def test_serialize_and_parse_resource_toml_round_trips() -> None:
    record = protocol.ResourceRecord(name="display", occupied=(1, 2, 5))

    parsed = state_files.parse_resource_toml(
        state_files.serialize_resource_toml(record), name="display", tip=_OTHER_TIP
    )

    assert parsed == record


@pytest.mark.parametrize(
    "content",
    [
        pytest.param('name = "display"\n', id="wrong-key"),
        pytest.param("occupied = [1, 0]\n", id="non-positive-value"),
        pytest.param('occupied = ["1"]\n', id="non-integer-value"),
        pytest.param("occupied = 1\n", id="not-a-list"),
    ],
)
def test_parse_resource_toml_rejects_a_malformed_record(content: str) -> None:
    with pytest.raises(protocol.MalformedStateTreeError):
        state_files.parse_resource_toml(content, name="display", tip=_OTHER_TIP)


def test_parse_resource_toml_rejects_malformed_toml() -> None:
    with pytest.raises(protocol.MalformedStateTreeError, match="malformed resource file"):
        state_files.parse_resource_toml("not = valid = toml\n", name="display", tip=_OTHER_TIP)


def _minimal_claim_toml_fields(**overrides: str) -> dict[str, str]:
    fields = {
        "claim_id": '"a1"',
        "agent": '"Ada"',
        "role": '"builder"',
        "base": f'"{CLAIM_BASE}"',
        "branch": '"claude/issue-42-cut"',
        "scope": '["README.md"]',
        "opened_commit": f'"{TIP}"',
    }
    fields.update(overrides)
    return fields


def _claim_toml_content(**overrides: str) -> str:
    fields = _minimal_claim_toml_fields(**overrides)
    return "\n".join(f"{key} = {value}" for key, value in fields.items()) + "\n"


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"agent": "123"}, "must be non-empty text", id="agent-not-text"),
        pytest.param({"agent": '""'}, "must be non-empty text", id="agent-empty"),
        pytest.param({"scope": "[]"}, "non-empty list of text", id="scope-empty"),
        pytest.param({"scope": "[1]"}, "non-empty list of text", id="scope-not-text"),
        pytest.param({"claim_id": '"not valid!"'}, "invalid claim id", id="claim-id-invalid"),
    ],
)
def test_parse_claim_toml_rejects_a_malformed_field(overrides: dict[str, str], match: str) -> None:
    content = _claim_toml_content(**overrides)
    with pytest.raises(protocol.MalformedStateTreeError, match=match):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_a_non_positive_resource_value() -> None:
    content = _claim_toml_content() + 'resource_name = "display"\nresource_value = 0\n'

    with pytest.raises(protocol.MalformedStateTreeError, match="positive integer"):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)


def test_parse_claim_toml_rejects_a_non_text_whole_reason() -> None:
    content = _claim_toml_content() + "whole_reason = 3\n"

    with pytest.raises(protocol.MalformedStateTreeError, match="must be text"):
        state_files.parse_claim_toml(content, key="issue-42", tip=_OTHER_TIP)
