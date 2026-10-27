"""The `whole` reason of a wide `aco claim`, on real temporary git worktrees
and the real state ref: which reason lands on the claim, the bound a reason
holds from the flag and from the item's body, and the refusals of a body whose
`whole` or `size` is defective. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from board_fixtures import complete_contract
from claim_worktrees import (
    ISSUE,
    StandIn,
    assert_no_item_body_written,
    claim,
    claimed_here,
    make_stand_in,
    serve_body,
    standing_claims,
)

WIDE_SCOPE = ["a.py", "b.py", "c.py", "d.py"]
BOUND_SENTENCE = "whole reason must be one bounded non-empty line"
WIDE_REFUSAL = "scope is wide: 4 paths exceeds three; pass --whole REASON or set whole in the body"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, tuple(WIDE_SCOPE))


@pytest.mark.parametrize(
    ("body_whole", "flags", "reason"),
    [
        pytest.param(
            "the four adapters share one lock",
            (),
            "the four adapters share one lock",
            id="the-items-own-body-whole",
        ),
        pytest.param(
            "the four adapters share one lock",
            ("--whole", "urgent, splitting later"),
            "urgent, splitting later",
            id="an-explicit-whole-wins-over-the-body",
        ),
        pytest.param("x" * 512, (), "x" * 512, id="the-body-boundary"),
    ],
)
def test_a_wide_derived_scope_takes_its_reason_from_the_flag_before_the_body(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    body_whole: str,
    flags: tuple[str, ...],
    reason: str,
) -> None:
    """Spec: CLM-21, BODY-61. A wide scope is admitted by the item's own
    `whole` exactly as by `--whole REASON`, an explicit `--whole` wins, and
    that sentence lands on the claim."""
    standpoint = stand_in()
    served = serve_body(
        monkeypatch, complete_contract("Ship it.", scope=WIDE_SCOPE, whole=body_whole)
    )

    status = claim("--claim-id", "cli-claim", *flags, scope=())

    assert status == 0
    assert capsys.readouterr().out.startswith(f"CLAIMED issue #{ISSUE}: cli-claim\n")
    assert claimed_here(standpoint).whole_reason == reason
    assert_no_item_body_written(served)


@pytest.mark.parametrize("source", ["flag", "body"])
@pytest.mark.parametrize(
    "value", ["x" * 513, "a\nb", " a", ""], ids=["long", "multiline", "padded", "empty"]
)
def test_a_whole_beyond_its_bound_is_refused_from_the_flag_and_from_the_body(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    source: str,
    value: str,
) -> None:
    """Spec: CLM-21, CLM-36, BODY-62. The flag and the body hold one bound."""
    standpoint = stand_in()
    body_whole = value if source == "body" else "ok"
    served = serve_body(
        monkeypatch, complete_contract("Ship it.", scope=["a.py"], whole=body_whole)
    )
    flags = ("--whole", value) if source == "flag" else ()

    status = claim(*flags, scope=())

    assert status == 2
    assert BOUND_SENTENCE in capsys.readouterr().err
    assert standing_claims(standpoint) == []
    assert_no_item_body_written(served)


@pytest.mark.parametrize(
    ("value", "scope", "flag", "reason", "field"),
    [
        pytest.param("x" * 513, (), None, "body_invalid", "whole", id="cell3"),
        pytest.param("a\nb", ("a.py",), None, "precondition_failed", "whole", id="cell4"),
        pytest.param(" a", tuple(WIDE_SCOPE), None, "body_invalid", "whole", id="cell5"),
        pytest.param(
            "x" * 513, tuple(WIDE_SCOPE), "ok", "precondition_failed", "whole", id="cell6"
        ),
        pytest.param("ok", tuple(WIDE_SCOPE), None, "body_invalid", "size", id="cell7"),
        pytest.param(None, tuple(WIDE_SCOPE), None, "unavailable", "", id="cell8"),
    ],
)
@pytest.mark.parametrize("as_json", [False, True], ids=["plain", "json"])
def test_a_body_with_a_defective_whole_or_size_refuses_by_its_first_defect_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    value: str | None,
    scope: tuple[str, ...],
    flag: str | None,
    reason: str,
    field: str,
    as_json: bool,
) -> None:
    """Spec: CLM-22, CLM-37, BODY-52, BODY-62. A fresh claim never writes the claim or
    the item, whichever of the body's defects or the width gate it meets."""
    standpoint = stand_in()
    entries: dict[str, str] = {} if value is None else {"whole": value}
    if field == "size":
        entries["size"] = "XL"
    served = serve_body(monkeypatch, complete_contract("Ship it.", scope=WIDE_SCOPE, **entries))
    flags = ("--whole", flag) if flag is not None else ()
    defect = "size must be S, M, or L" if field == "size" else BOUND_SENTENCE
    label = f"#{ISSUE} " if reason == "body_invalid" else ""
    expected = f"ERROR: {label}body malformed: {field}: {defect}\n"
    if reason == "unavailable":
        expected = f"ERROR: {WIDE_REFUSAL}\n"

    status = claim(*flags, *(("--json",) if as_json else ()), scope=scope)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.err == ("" if as_json and reason == "precondition_failed" else expected)
    if as_json:
        payload = json.loads(captured.out)
        assert payload["reason"] == reason
        if reason == "precondition_failed":
            assert payload["checks"]
    assert standing_claims(standpoint) == []
    assert_no_item_body_written(served)
