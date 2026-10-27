"""`aco claim --json` beside the claims others already hold, on real temporary
git worktrees and the real state ref: the standing claims it lists as touches
and the value a shared resource allocates. The forge is the only fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from claim_worktrees import (
    StandIn,
    Standing,
    claim,
    claimed_here,
    make_stand_in,
    serve_item,
    standing_claims,
)

from aco import protocol

TRUNK_FILES = ("src/widget.py", "src/work.py", "LICENSE", "tests/adapters/test_claim_cli.py")
RESOURCE = "schema-hop"


@pytest.fixture
def stand_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> StandIn:
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, TRUNK_FILES)


def touch(issue: int, scope: list[str]) -> dict[str, object]:
    return {"issue": issue, "lane": None, "claim_id": "held-0", "agent": "Ada", "scope": scope}


@pytest.mark.parametrize(
    ("standing", "own_scope", "touches"),
    [
        pytest.param(Standing(("LICENSE",), issue=73), ("src",), [], id="a-disjoint-claim"),
        pytest.param(
            Standing(("src",), issue=73),
            ("src/work.py",),
            [touch(73, ["src"])],
            id="a-standing-directory-over-our-file",
        ),
        pytest.param(
            Standing(("tests/adapters/test_claim_cli.py",), issue=1400),
            ("tests",),
            [touch(1400, ["tests/adapters/test_claim_cli.py"])],
            id="a-standing-file-under-our-directory",
        ),
    ],
)
def test_claim_json_lists_each_overlapping_standing_claim_with_its_full_scope(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    standing: Standing,
    own_scope: tuple[str, ...],
    touches: list[dict[str, object]],
) -> None:
    """Spec: CLM-19, CLAIM-31, CLAIM-32."""
    stand_in(standing=(standing,))
    serve_item(monkeypatch, own_scope)

    status = claim("--json", scope=own_scope)

    assert status == 0
    assert json.loads(capsys.readouterr().out)["touches"] == touches


@pytest.mark.parametrize(
    ("standing", "values"),
    [
        pytest.param((), [1], id="the-first-holder-gets-one"),
        pytest.param(
            (Standing(("src/widget.py",), issue=73, resource=RESOURCE),),
            [1, 2],
            id="a-second-holder-gets-two",
        ),
    ],
)
def test_claim_resource_allocates_the_next_value_and_prints_it(
    monkeypatch: pytest.MonkeyPatch,
    stand_in: StandIn,
    capsys: pytest.CaptureFixture[str],
    standing: tuple[Standing, ...],
    values: list[int],
) -> None:
    """Spec: CLAIM-41."""
    standpoint = stand_in(standing=standing)
    serve_item(monkeypatch, ("src/work.py",))

    status = claim("--resource", RESOURCE, "--json", scope=("src/work.py",))

    assert status == 0
    assert json.loads(capsys.readouterr().out)["resource_value"] == values[-1]
    assert claimed_here(standpoint).resource == protocol.ResourceHold(RESOURCE, values[-1])
    held = sorted(
        held.resource.value
        for held in standing_claims(standpoint)
        if held.resource is not None and held.resource.name == RESOURCE
    )
    assert held == values
