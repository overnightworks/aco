"""The per-item turn's card writer (`specs/mcp.spec.md`) on a fake forge, on both
storage pins."""

from datetime import date
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import track_board_config
from github_fixtures import FakeForge
from option_cards import SECOND_CARD, ask_card, card, other_card, returned_card, ruled_card

from aco import body, decide, expectations, forge, protocol
from aco.session import RunContext

TODAY = date(2026, 11, 8)
NUMBER = 90
STORAGE_PINS = [
    pytest.param(body.Storage.GITHUB, id="github"),
    pytest.param(body.Storage.STATE_REF, id="state-ref"),
]


def item_with(*lines: str, minimal: str = MINIMAL_BLOCK_TOML) -> str:
    return block_body(minimal + "\n".join(lines))


def world(
    clone: Path,
    item_body: str,
    *,
    storage: body.Storage = body.Storage.GITHUB,
    state: forge.ItemState = forge.ItemState.OPEN,
    author_is_member: bool = True,
    client: FakeForge | None = None,
) -> tuple[RunContext, FakeForge]:
    """A checkout pinned to `storage` whose item 90 is `item_body`, behind a fake forge."""
    track_board_config(clone, f'storage = "{storage.value}"\n')
    reference = forge.ItemReference(state, "Titel", item_body, author_is_member=author_is_member)
    served = client or FakeForge()
    served.issue_references[NUMBER] = reference
    return RunContext(None, build_forge=lambda _context: served, today=lambda: TODAY), served


def ask(context: RunContext, card_to_ask: dict[str, object] | None = None) -> decide.Asked:
    fresh = decide.fresh_item(context, NUMBER, command="ask")
    return decide.ask(context, fresh, ask_card() if card_to_ask is None else card_to_ask)


def option_lines(raw: str, storage: body.Storage = body.Storage.GITHUB) -> list[object]:
    return [
        line
        for line in expectations.expectation_lines(raw, storage=storage)
        if isinstance(line, expectations.OptionLine)
    ]


@pytest.mark.parametrize("storage", STORAGE_PINS)
def test_a_card_is_written_once_over_the_body_it_read_and_answered_with_its_stored_line(
    storage: body.Storage, clone: Path
) -> None:
    before = item_with(SECOND_CARD)
    context, client = world(clone, before, storage=storage)

    asked = ask(context)

    written = client.item_bodies[NUMBER]
    *_, stored = expectations.expectation_lines(written, storage=storage)
    assert (asked.written, client.body_writes) == (True, [(NUMBER, written)])
    assert client.body_replacings == [before]
    assert asked.line == stored
    assert (asked.line.index, asked.line.asked_on, asked.line.ruling) == (2, TODAY, None)


@pytest.mark.parametrize(
    ("state", "author_is_member", "sentence"),
    [
        pytest.param(forge.ItemState.CLOSED, True, "is closed", id="closed"),
        pytest.param(forge.ItemState.OPEN, False, "not written by a member", id="non-member"),
    ],
)
def test_an_item_that_shows_nowhere_refuses_and_writes_nothing(
    state: forge.ItemState, author_is_member: bool, sentence: str, clone: Path
) -> None:
    context, client = world(
        clone, item_with(card()), state=state, author_is_member=author_is_member
    )

    with pytest.raises(protocol.ClaimError, match=sentence):
        ask(context)

    assert client.body_writes == []


@pytest.mark.parametrize(
    ("changes", "sentence"),
    [
        pytest.param({"text": ["a"]}, "must be a non-empty string", id="a-list-for-a-string"),
        pytest.param({"area": 4}, "must be a non-empty string", id="an-integer-for-a-string"),
    ],
)
def test_a_value_the_grammar_refuses_writes_nothing(
    changes: dict[str, object], sentence: str, clone: Path
) -> None:
    context, client = world(clone, item_with(card()))
    asked = ask_card(**changes)

    with pytest.raises(protocol.ClaimError, match=sentence):
        ask(context, asked)

    assert client.body_writes == []


@pytest.mark.parametrize(
    "standing",
    [
        pytest.param(card(), id="open"),
        pytest.param(ruled_card(), id="ruled"),
        pytest.param(other_card(), id="ruled-other"),
        pytest.param(returned_card(), id="returned"),
    ],
)
def test_the_same_card_asked_again_answers_the_line_that_stands_and_writes_nothing(
    standing: str, clone: Path
) -> None:
    context, client = world(clone, item_with(standing))

    asked = ask(context)

    [line] = option_lines(item_with(standing))
    assert (asked.written, asked.line, client.body_writes) == (False, line, [])


def test_hand_edits_that_left_several_equal_cards_answer_the_first_by_index(clone: Path) -> None:
    context, client = world(clone, item_with(card(), card()))

    asked = ask(context)

    assert (asked.written, asked.line.index, client.body_writes) == (False, 1, [])


def test_a_card_asked_again_after_its_line_was_withdrawn_is_written_as_a_new_line(
    clone: Path,
) -> None:
    withdrawn = expectations.withdraw_line(item_with(card()), 1, TODAY)
    context, client = world(clone, withdrawn)

    asked = ask(context)

    assert (asked.written, asked.line.index, len(client.body_writes)) == (True, 2, 1)


def test_a_card_the_card_rules_refuse_writes_nothing(clone: Path) -> None:
    context, client = world(clone, item_with(card()))
    asked = ask_card(problem="Dieses Problem " + "braucht viel zu viele Wörter " * 8)

    with pytest.raises(protocol.ClaimError, match="must be at most 20 words"):
        ask(context, asked)

    assert client.body_writes == []


def test_a_picture_holding_a_fence_line_would_malform_the_body_and_is_refused(
    clone: Path,
) -> None:
    context, client = world(clone, item_with(card()))
    asked = ask_card(picture="<svg/>\n```\nclosed early")

    with pytest.raises(protocol.ClaimError, match="body malformed"):
        ask(context, asked)

    assert client.body_writes == []


def test_an_item_whose_body_is_incomplete_refuses_a_new_card_with_the_missing_sections(
    clone: Path,
) -> None:
    emptied = 'version = 1\nnow = ""\nnext = "X"\ndone_when = "D"\n'
    context, client = world(clone, item_with(minimal=emptied))

    with pytest.raises(protocol.ClaimError, match="body incomplete: Now"):
        ask(context)

    assert client.body_writes == []


def test_a_repeat_answers_although_the_item_has_since_become_incomplete(clone: Path) -> None:
    emptied = 'version = 1\nnow = ""\nnext = "X"\ndone_when = "D"\n'
    context, client = world(clone, item_with(card(), minimal=emptied))

    asked = ask(context)

    assert (asked.written, client.body_writes) == (False, [])


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(forge.ForgeBodyNotVerifiedError(NUMBER, "no history"), id="not-verified"),
        pytest.param(
            forge.ForgeBodyOverwrittenError(NUMBER, "2026-11-08T09:00:00Z", "editor", kept=False),
            id="overwritten-lost",
        ),
        pytest.param(
            forge.ForgeBodyOverwrittenError(NUMBER, "2026-11-08T09:00:00Z", "editor", kept=True),
            id="overwritten-kept",
        ),
    ],
)
def test_the_body_write_checks_answer_passes_through_and_a_repeat_after_it_writes_nothing(
    answer: forge.ForgeBodyWrittenError, clone: Path
) -> None:
    context, client = world(
        clone,
        item_with(SECOND_CARD),
        client=FakeForge(update_item_body_error=answer, update_item_body_lands_before_error=True),
    )

    with pytest.raises(forge.ForgeBodyWrittenError) as refused:
        ask(context)
    standing = client.item_bodies[NUMBER]
    after = FakeForge(
        issue_references={
            NUMBER: forge.ItemReference(
                forge.ItemState.OPEN, "Titel", standing, author_is_member=True
            )
        }
    )
    asked_again = ask(RunContext(None, build_forge=lambda _context: after, today=lambda: TODAY))

    assert refused.value is answer
    assert (asked_again.written, asked_again.line.index, after.body_writes) == (False, 2, [])
