"""`claims/<key>.toml` and `resources/<name>.toml` codecs: the file format of the
claim state tree's claim and resource entries, apart from the pure transitions
in `protocol` that decide what those entries hold.
"""

import tomllib
from collections.abc import Mapping

from .protocol import (
    CLAIM_ID_PATTERN,
    COMMIT_PATTERN,
    ActiveClaim,
    ClaimId,
    InvalidClaimMarkerError,
    MalformedStateTreeError,
    ObjectId,
    ResourceHold,
    ResourceRecord,
    parse_claim_key,
    valid_scope,
)
from .toml_text import toml_string


def _toml_string_array(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(toml_string(value) for value in values) + "]"


def _toml_int_array(values: tuple[int, ...]) -> str:
    return "[" + ", ".join(str(value) for value in values) + "]"


def serialize_claim_toml(claim: ActiveClaim) -> str:
    """The `claims/<key>.toml` content for one live claim (claim-record.spec.md, CLAIM-05)."""
    lines = [
        f"claim_id = {toml_string(claim.claim_id)}",
        f"agent = {toml_string(claim.agent)}",
        f"role = {toml_string(claim.role)}",
        f"base = {toml_string(claim.base)}",
        f"branch = {toml_string(claim.branch)}",
        f"scope = {_toml_string_array(claim.scope)}",
        f"opened_commit = {toml_string(claim.opened_commit)}",
    ]
    if claim.whole_reason is not None:
        lines.append(f"whole_reason = {toml_string(claim.whole_reason)}")
    if claim.resource is not None:
        lines.append(f"resource_name = {toml_string(claim.resource.name)}")
        lines.append(f"resource_value = {claim.resource.value}")
    return "\n".join(lines) + "\n"


_CLAIM_TOML_REQUIRED_KEYS = frozenset(
    {"claim_id", "agent", "role", "base", "branch", "scope", "opened_commit"}
)
_CLAIM_TOML_OPTIONAL_KEYS = frozenset({"whole_reason", "resource_name", "resource_value"})
_CLAIM_TOML_KEYS = _CLAIM_TOML_REQUIRED_KEYS | _CLAIM_TOML_OPTIONAL_KEYS


def _claim_toml_text(
    data: Mapping[str, object], field_name: str, *, key: str, tip: ObjectId
) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} field {field_name!r} must be non-empty text"
        )
    return value


def _claim_toml_scope(data: Mapping[str, object], *, key: str, tip: ObjectId) -> tuple[str, ...]:
    """`data`'s `scope` field, projected through `valid_scope`, the one
    canonicalizer a claim's scope passes through at creation and rescope: a
    claim file whose paths are in another order reads back equal to its
    canonical form. A read never rewrites the ref, and it
    refuses only content `valid_scope` refuses from a fresh request, such as a
    non-repository-relative or duplicated path."""
    raw = data.get("scope")
    if not isinstance(raw, list) or not raw or any(not isinstance(entry, str) for entry in raw):
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} field 'scope' must be a non-empty list of text"
        )
    try:
        return valid_scope(raw)
    except InvalidClaimMarkerError as error:
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} has an invalid scope: {error}"
        ) from error


def _claim_toml_resource(
    data: Mapping[str, object], *, key: str, tip: ObjectId
) -> ResourceHold | None:
    if "resource_name" not in data:
        if "resource_value" in data:
            raise MalformedStateTreeError(
                f"claim file {key}.toml at {tip} has resource_value without resource_name"
            )
        return None
    name = _claim_toml_text(data, "resource_name", key=key, tip=tip)
    value = data.get("resource_value")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} field 'resource_value' must be a positive integer"
        )
    return ResourceHold(name, value)


def parse_claim_toml(content: str, *, key: str, tip: ObjectId) -> ActiveClaim:
    """Parse one fetched `claims/<key>.toml` blob into its `ActiveClaim`.

    A malformed claim file fails the whole read loud (a commit is the
    unit a writer writes, so a broken tree is corrupt state, never a single
    quarantinable claim).
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise MalformedStateTreeError(
            f"malformed claim file {key}.toml at {tip}: {error}"
        ) from error
    observed_keys = frozenset(data)
    if not observed_keys <= _CLAIM_TOML_KEYS:
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} has unknown keys: "
            f"{sorted(observed_keys - _CLAIM_TOML_KEYS)}"
        )
    missing = _CLAIM_TOML_REQUIRED_KEYS - observed_keys
    if missing:
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} is missing {sorted(missing)}"
        )
    identity = parse_claim_key(key)
    claim_id_text = _claim_toml_text(data, "claim_id", key=key, tip=tip)
    if CLAIM_ID_PATTERN.fullmatch(claim_id_text) is None:
        raise MalformedStateTreeError(f"claim file {key}.toml at {tip} has an invalid claim id")
    base_text = _claim_toml_text(data, "base", key=key, tip=tip)
    opened_commit_text = _claim_toml_text(data, "opened_commit", key=key, tip=tip)
    commit_fields_valid = (
        COMMIT_PATTERN.fullmatch(base_text) is not None
        and COMMIT_PATTERN.fullmatch(opened_commit_text) is not None
    )
    if not commit_fields_valid:
        raise MalformedStateTreeError(f"claim file {key}.toml at {tip} has a malformed commit id")
    whole_reason = data.get("whole_reason")
    if whole_reason is not None and not isinstance(whole_reason, str):
        raise MalformedStateTreeError(
            f"claim file {key}.toml at {tip} field 'whole_reason' must be text"
        )
    return ActiveClaim(
        identity=identity,
        claim_id=ClaimId(claim_id_text),
        agent=_claim_toml_text(data, "agent", key=key, tip=tip),
        role=_claim_toml_text(data, "role", key=key, tip=tip),
        base=ObjectId(base_text),
        branch=_claim_toml_text(data, "branch", key=key, tip=tip),
        scope=_claim_toml_scope(data, key=key, tip=tip),
        opened_commit=ObjectId(opened_commit_text),
        resource=_claim_toml_resource(data, key=key, tip=tip),
        whole_reason=whole_reason,
    )


def serialize_resource_toml(record: ResourceRecord) -> str:
    """The `resources/<name>.toml` content of one resource (ref-store-cas.spec.md, CAS-35)."""
    return f"occupied = {_toml_int_array(record.occupied)}\n"


def parse_resource_toml(content: str, *, name: str, tip: ObjectId) -> ResourceRecord:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        raise MalformedStateTreeError(
            f"malformed resource file {name}.toml at {tip}: {error}"
        ) from error
    if set(data) != {"occupied"}:
        raise MalformedStateTreeError(
            f"resource file {name}.toml at {tip} must contain exactly 'occupied'"
        )
    occupied = data["occupied"]
    if not isinstance(occupied, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in occupied
    ):
        raise MalformedStateTreeError(
            f"resource file {name}.toml at {tip} field 'occupied' must be positive integers"
        )
    return ResourceRecord(name=name, occupied=tuple(occupied))
