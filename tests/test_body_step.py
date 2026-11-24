"""The block's `step` table through the body codec (`specs/body-block.spec.md`): a
defective one makes the body malformed and a rewrite of the block keeps a valid one of
either shape key for key."""

import json

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, complete_contract
from cli_fixtures import run_cli
from github_fixtures import FakeForge, serve_forge
from option_cards import card, decide, ruled_card

from aco import body, cmd_item_edit, forge
from aco.decide import FreshItem

_PASTE_TABLE = {"purpose": "Why.", "paste": "cd repo\n./rotate && done", "expected": "See that."}
_OLD_TABLE = {"purpose": "Why.", "actions": "Do\nthis.", "expected": "See that."}
_TABLES = [
    pytest.param(_PASTE_TABLE, id="paste"),
    pytest.param(_OLD_TABLE, id="actions"),
    pytest.param({**_OLD_TABLE, "answer": "Say."}, id="actions-and-answer"),
]


def _table(**changes: object) -> dict[str, object]:
    return {**_PASTE_TABLE, **changes}


def _hand_written(step: dict[str, object]) -> str:
    """A body whose `[step]` table is written key by key as an author would, so a table
    the production writer cannot render still reaches the reader."""
    lines = (f"{key} = {json.dumps(value)}" for key, value in step.items())
    return block_body(MINIMAL_BLOCK_TOML + "[step]\n" + "\n".join(lines) + "\n")


def _with_expectations(step: dict[str, object]) -> str:
    """A body whose block holds `step` ahead of one ruled and one open option line."""
    held = complete_contract("Next.", step=step)
    located = body.locate_block(held)
    head = held[located.content_start : located.content_end].rstrip("\n")
    return block_body(head + "\n\n" + "\n".join((ruled_card(), card())))


@pytest.mark.parametrize(
    "step",
    [pytest.param(_PASTE_TABLE, id="paste"), pytest.param(_OLD_TABLE, id="actions")],
)
def test_a_body_with_a_valid_step_table_is_valid(step: dict[str, object]) -> None:
    """Spec: BODY-123, BODY-126"""
    parsed = body.parse_body(complete_contract("Next.", step=step))

    assert parsed.read_state is body.BodyReadState.VALID


def test_a_body_without_a_step_table_is_valid() -> None:
    """Spec: BODY-122"""
    parsed = body.parse_body(complete_contract("Next."))

    assert parsed.read_state is body.BodyReadState.VALID


@pytest.mark.parametrize(
    ("step", "fields"),
    [
        pytest.param(_table(purpose=" "), ["step.purpose"], id="blank-purpose"),
        pytest.param(_table(paste=" "), ["step.paste"], id="blank-paste"),
        pytest.param(
            {"purpose": "Why.", "expected": "See that."},
            ["step.paste"],
            id="neither-paste-nor-actions",
        ),
        pytest.param(_table(actions="Do this."), ["step.actions"], id="paste-and-actions"),
        pytest.param(_table(answer="Say."), ["step.answer"], id="paste-and-answer"),
        pytest.param(_table(colour="red"), ["step.colour"], id="paste-and-unknown-key"),
        pytest.param({**_OLD_TABLE, "actions": " "}, ["step.actions"], id="blank-actions"),
        pytest.param(
            {**_OLD_TABLE, "colour": "red"}, ["step.colour"], id="actions-and-unknown-key"
        ),
    ],
)
def test_a_body_with_a_defective_step_table_is_refused_naming_the_field(
    step: dict[str, object], fields: list[str]
) -> None:
    """Spec: BODY-124, BODY-127"""
    parsed = body.parse_body(_hand_written(step))

    assert parsed.read_state is body.BodyReadState.MALFORMED
    assert [defect.field for defect in parsed.contract.defects] == fields


@pytest.mark.parametrize("newline", [pytest.param("\n", id="lf"), pytest.param("\r\n", id="crlf")])
@pytest.mark.parametrize("step", _TABLES)
def test_rewriting_the_block_keeps_the_step_table_key_for_key(
    step: dict[str, object], newline: str
) -> None:
    """Spec: BODY-125, BODY-128"""
    held = complete_contract("Next.", step=step).replace("\n", newline)
    located = body.locate_block(held)

    rewritten = body.replace_block(held, located, {**located.data, "next": "Other."})

    assert body.locate_block(rewritten).data["step"] == step


@pytest.mark.parametrize("step", _TABLES)
def test_the_step_table_stands_ahead_of_every_expectation_after_a_rewrite(
    step: dict[str, object],
) -> None:
    """Spec: BODY-125"""
    held = _with_expectations(step)
    located = body.locate_block(held)

    rewritten = body.replace_block(held, located, located.data)

    assert rewritten.index("[step]") < rewritten.index("[[expectation]]")


@pytest.mark.usefixtures("github_world")
@pytest.mark.parametrize("step", _TABLES)
def test_a_ruling_keeps_the_step_table_key_for_key(
    step: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BODY-128"""
    held = _with_expectations(step)
    reference = forge.ItemReference(forge.ItemState.OPEN, "Karte", held)
    client = serve_forge(monkeypatch, FakeForge(issue_references={7: reference}))

    ruled = run_cli(["rule", "7", *decide("A", "chat", line=2)], capsys)

    assert ruled.status == 0, ruled.stderr
    assert body.locate_block(client.item_bodies[7]).data["step"] == step


@pytest.mark.parametrize("step", _TABLES)
def test_an_item_edit_write_keeps_the_step_table_key_for_key(step: dict[str, object]) -> None:
    """Spec: BODY-128"""
    held = _with_expectations(step)
    located = body.locate_block(held)
    client = FakeForge()
    fresh = FreshItem(7, "", held, body.Storage.GITHUB, forge.ItemState.OPEN, located, True)

    cmd_item_edit.write_block_data(client, fresh, {**located.data, "next": "Weiter."})

    assert body.locate_block(client.item_bodies[7]).data["step"] == step


@pytest.mark.usefixtures("clone")
@pytest.mark.parametrize(
    ("step", "status", "stdout", "stderr"),
    [
        pytest.param(_PASTE_TABLE, 0, "body ok\n", "", id="multi-line-paste"),
        pytest.param(_OLD_TABLE, 0, "body ok\n", "", id="actions"),
        pytest.param(
            _table(actions="Open the link."),
            2,
            "",
            "body malformed: step.actions: unknown key step.actions\n",
            id="paste-and-actions",
        ),
    ],
)
def test_check_prints_the_verdict_on_a_step_table(
    capsys: pytest.CaptureFixture[str],
    step: dict[str, object],
    status: int,
    stdout: str,
    stderr: str,
) -> None:
    """Spec: BODY-123, BODY-126, BODY-127. Example: E-BODY-22."""
    result = run_cli(["check", "-"], capsys, stdin=_hand_written(step))

    assert (result.status, result.stdout, result.stderr) == (status, stdout, stderr)
