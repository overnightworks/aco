"""A whole-body `aco item edit` of an idea's body, which carries no aco block
(`specs/item.spec.md` ITEM-79, ITEM-80), on a GitHub-hosted board whose forge is the
only fake."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_cli
from github_fixtures import serve_forge
from item_base import edit_with_base
from item_lock_witness import LockWitnessForge

from aco import forge, workboard

pytestmark = pytest.mark.usefixtures("github_world")

NUMBER = 72
IDEA_BODY = "An idea in prose.\n"
NO_BLOCK_DEFECT = "body malformed: aco: no aco block"

type ServeItem = Callable[[tuple[str, ...]], LockWitnessForge]


@pytest.fixture
def serve_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ServeItem:
    """Serves item `NUMBER`, open with the prose-only body and the given labels."""

    def serve(labels: tuple[str, ...]) -> LockWitnessForge:
        reference = forge.ItemReference(forge.ItemState.OPEN, "Idea", IDEA_BODY, labels=labels)
        client = LockWitnessForge(tmp_path / "item-locks", issue_references={NUMBER: reference})
        return serve_forge(monkeypatch, client)

    return serve


def test_an_idea_body_with_no_block_is_written_against_its_base(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-79."""
    client = serve_item((workboard.DEFAULT_IDEA_LABEL,))
    arguments = edit_with_base(str(NUMBER), capsys)
    replacement = "A reworded idea.\n"

    result = run_cli(arguments, capsys, stdin=replacement)

    assert (result.status, result.stdout) == (0, f"EDITED #{NUMBER}\n")
    assert client.item_bodies == {NUMBER: replacement}


def test_an_idea_body_edited_from_a_stale_base_refuses_and_writes_nothing(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-79, ITEM-72."""
    client = serve_item((workboard.DEFAULT_IDEA_LABEL,))
    arguments = edit_with_base(str(NUMBER), capsys)
    client.item_bodies[NUMBER] = "Reworded meanwhile.\n"

    result = run_cli([*arguments, "--json"], capsys, stdin="Mine.\n")

    assert (result.status, json.loads(result.stdout)["reason"]) == (2, "stale")
    assert client.body_writes == []


@pytest.mark.parametrize(
    ("labels", "stdin", "defect"),
    [
        pytest.param((), "No block.\n", NO_BLOCK_DEFECT, id="no-label-no-block"),
        pytest.param(
            (workboard.DEFAULT_IDEA_LABEL,),
            "```aco\nversion = \n```\n",
            None,
            id="idea-with-malformed-block",
        ),
    ],
)
def test_a_body_the_item_cannot_excuse_refuses_body_invalid(
    serve_item: ServeItem,
    capsys: pytest.CaptureFixture[str],
    labels: tuple[str, ...],
    stdin: str,
    defect: str | None,
) -> None:
    """Spec: ITEM-80 -- no idea label, or a block that does not read, refuses as today."""
    client = serve_item(labels)
    arguments = edit_with_base(str(NUMBER), capsys)

    result = run_cli([*arguments, "--json"], capsys, stdin=stdin)

    envelope = json.loads(result.stdout)
    assert (result.status, envelope["reason"]) == (2, "body_invalid")
    if defect is not None:
        assert envelope["defects"] == [defect]
    assert client.body_writes == []


def test_an_idea_body_with_a_valid_block_is_written_as_any_body(
    serve_item: ServeItem, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: ITEM-80 -- a body carrying a block is checked as ever, labelled or not."""
    client = serve_item((workboard.DEFAULT_IDEA_LABEL,))
    arguments = edit_with_base(str(NUMBER), capsys)
    replacement = block_body(MINIMAL_BLOCK_TOML)

    result = run_cli(arguments, capsys, stdin=replacement)

    assert (result.status, client.item_bodies) == (0, {NUMBER: replacement})
