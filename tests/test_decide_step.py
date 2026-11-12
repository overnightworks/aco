"""The per-item turn's step writer (`specs/mcp.spec.md`) on a fake forge: the
`next` it folds in, the order of the body and the label, and what it refuses."""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, searchless
from cli_fixtures import track_board_config
from github_fixtures import FakeForge
from option_cards import card, ruled_card

from aco import body, decide, forge, protocol, workboard
from aco.session import RunContext

NUMBER = 90
STEP = "Rotate the deploy key."


@dataclass
class _LabelWitness(FakeForge):
    """A fake forge that keeps the body the item held at each label call."""

    bodies_at_label: list[str | None] = field(default_factory=list[str | None])

    def add_label(self, number: int, label: str) -> None:
        self.bodies_at_label.append(self.item_bodies.get(number))
        super().add_label(number, label)


def _stepped_item() -> str:
    block = MINIMAL_BLOCK_TOML + 'scope = ["src/a.py"]\n' + "\n".join((ruled_card(), card()))
    return block_body(block, before="Prose before, with `code`.\n\n", after="\nAfter.\n")


def _world(
    clone: Path,
    item_body: str,
    *,
    state: forge.ItemState = forge.ItemState.OPEN,
    author_is_member: bool = True,
) -> tuple[RunContext, _LabelWitness]:
    track_board_config(clone, 'storage = "github"\n')
    served = _LabelWitness()
    served.issue_references[NUMBER] = forge.ItemReference(
        state, "Titel", item_body, author_is_member=author_is_member
    )
    context = searchless(None, build_forge=lambda _context: served, today=lambda: date(2026, 11, 8))
    return context, served


def _mark(context: RunContext, step: str = STEP) -> None:
    fresh = decide.fresh_item(context, NUMBER, command="step")
    decide.mark_step(context, fresh, step)


def test_the_step_replaces_next_and_keeps_every_other_field_and_byte(clone: Path) -> None:
    before = _stepped_item()
    context, client = _world(clone, before)

    _mark(context)

    written = client.item_bodies[NUMBER]
    old, new = body.locate_block(before), body.locate_block(written)
    assert new.data == {**old.data, "next": STEP}
    assert written[: new.content_start] == before[: old.content_start]
    assert written[new.content_end :] == before[old.content_end :]
    assert client.body_replacings == [before]


def test_the_label_is_set_after_the_body_is_written(clone: Path) -> None:
    context, client = _world(clone, _stepped_item())

    _mark(context)

    assert client.bodies_at_label == [client.item_bodies[NUMBER]]
    assert client.added_labels == [(NUMBER, workboard.NEEDS_OPERATOR_LABEL)]


@pytest.mark.parametrize(
    ("state", "author_is_member", "sentence"),
    [
        pytest.param(forge.ItemState.CLOSED, True, "is closed", id="closed"),
        pytest.param(forge.ItemState.OPEN, False, "not written by a member", id="non-member"),
    ],
)
def test_an_item_that_shows_nowhere_is_refused_before_any_write(
    state: forge.ItemState, author_is_member: bool, sentence: str, clone: Path
) -> None:
    context, client = _world(clone, _stepped_item(), state=state, author_is_member=author_is_member)

    with pytest.raises(protocol.ClaimError, match=sentence):
        _mark(context)

    assert (client.body_writes, client.added_labels) == ([], [])


def test_a_repeat_writes_no_body_and_still_calls_the_label(clone: Path) -> None:
    context, client = _world(clone, _stepped_item())
    _mark(context)
    client.issue_references[NUMBER] = forge.ItemReference(
        forge.ItemState.OPEN, "Titel", client.item_bodies[NUMBER], author_is_member=True
    )

    _mark(context)

    assert len(client.body_writes) == 1
    assert client.added_labels == [(NUMBER, workboard.NEEDS_OPERATOR_LABEL)] * 2


def test_a_failed_body_check_refuses_with_its_sentence_and_sets_no_label(clone: Path) -> None:
    context, client = _world(clone, _stepped_item())
    check_answer = forge.ForgeBodyNotVerifiedError(NUMBER, "timeout")
    client.update_item_body_error = check_answer

    with pytest.raises(forge.ForgeBodyNotVerifiedError, match="timeout"):
        _mark(context)

    assert client.added_labels == []


def test_a_failed_label_says_the_step_stands_and_a_repeat_sets_the_label(clone: Path) -> None:
    context, client = _world(clone, _stepped_item())
    client.add_label_error = forge.ForgeError("HTTP 403")

    with pytest.raises(protocol.ClaimError, match="HTTP 403") as refused:
        _mark(context)
    client.add_label_error = None
    client.issue_references[NUMBER] = forge.ItemReference(
        forge.ItemState.OPEN, "Titel", client.item_bodies[NUMBER], author_is_member=True
    )
    _mark(context)

    assert "label" in str(refused.value)
    assert "repeat" in str(refused.value)
    assert len(client.body_writes) == 1
    assert client.added_labels == [(NUMBER, workboard.NEEDS_OPERATOR_LABEL)] * 2
