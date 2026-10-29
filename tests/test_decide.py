"""The shared ruling writer (`specs/rule.spec.md`) on a fake forge, on both storage pins."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from cli_fixtures import run_context_over, track_board_config
from github_fixtures import FakeForge
from option_cards import GOLDEN_CARD_HASH, card, ruled_card

from aco import body, decide, expectations, forge, protocol
from aco.session import RunContext

TODAY = date(2026, 10, 29)
TITLE = "Entscheidung"
STORAGE_PINS = [
    pytest.param(body.Storage.GITHUB, id="github"),
    pytest.param(body.Storage.STATE_REF, id="state-ref"),
]


def item_with(*lines: str) -> str:
    return block_body(MINIMAL_BLOCK_TOML + "\n".join(lines))


def choose(index: int, card_hash: str = GOLDEN_CARD_HASH) -> decide.LineOutcome:
    choice = expectations.OptionChoice("A", expectations.RulingVia.CHAT, card_hash)
    return decide.LineOutcome(index, choice)


def world(storage: body.Storage, item_body: str, clone: Path) -> tuple[RunContext, FakeForge]:
    """A checkout pinned to `storage` whose issue 90 is `item_body`, behind a fake forge."""
    track_board_config(clone, f'storage = "{storage.value}"\n')
    reference = forge.ItemReference(forge.ItemState.OPEN, TITLE, item_body)
    client = FakeForge(issue_references={90: reference})
    return run_context_over(client), client


@pytest.mark.parametrize("storage", STORAGE_PINS)
class TestCommitted:
    def test_committed_lines_are_the_expectation_lines_of_the_written_body(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), card()), clone)
        committed = decide.rule(context, decide.fresh_item(context, 90), [choose(2)], TODAY)
        written = client.item_bodies[90]
        assert committed.lines == tuple(expectations.expectation_lines(written, storage=storage))
        assert [line.ruling for line in committed.lines] == [None, "A"]

    def test_committed_carries_the_title_of_the_item_the_gate_read(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card()), clone)
        committed = decide.rule(context, decide.fresh_item(context, 90), [choose(1)], TODAY)
        assert (committed.number, committed.title) == (90, TITLE)

    def test_committed_counts_the_lines_still_open(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card(), card(), card()), clone)
        committed = decide.rule(context, decide.fresh_item(context, 90), [choose(2)], TODAY)
        assert committed.open_remaining == 2

    def test_two_named_lines_land_in_one_write(self, storage: body.Storage, clone: Path) -> None:
        context, client = world(storage, item_with(card(), card()), clone)
        committed = decide.rule(
            context, decide.fresh_item(context, 90), [choose(1), choose(2)], TODAY
        )
        assert len(client.body_writes) == 1
        assert [line.ruling for line in committed.lines] == ["A", "A"]

    @pytest.mark.parametrize(
        "item_body,named,refusal",
        [
            pytest.param(
                item_with(ruled_card()),
                [choose(1)],
                expectations.ExpectationAlreadyRuledError,
                id="already-ruled",
            ),
            pytest.param(
                item_with(card()),
                [choose(1, "sha256:" + "0" * 64)],
                expectations.ExpectationCardChangedError,
                id="card-changed",
            ),
            pytest.param(
                item_with(card()),
                [choose(2)],
                expectations.ExpectationOutOfRangeError,
                id="out-of-range",
            ),
            pytest.param(
                item_with(card(), ruled_card()),
                [choose(1), choose(2)],
                expectations.ExpectationAlreadyRuledError,
                id="second-named-line-refused",
            ),
        ],
    )
    def test_a_refusal_writes_nothing(
        self,
        storage: body.Storage,
        item_body: str,
        named: list[decide.LineOutcome],
        refusal: type[protocol.ClaimError],
        clone: Path,
    ) -> None:
        context, client = world(storage, item_body, clone)
        fresh = decide.fresh_item(context, 90)
        with pytest.raises(refusal):
            decide.rule(context, fresh, named, TODAY)
        assert client.body_writes == []

    @pytest.mark.parametrize(
        "reference",
        [
            pytest.param(forge.ItemReference(forge.ItemState.MISSING), id="missing"),
            pytest.param(
                forge.ItemReference(forge.ItemState.OPEN, TITLE, "no block", is_landing=True),
                id="pull-request",
            ),
            pytest.param(
                forge.ItemReference(forge.ItemState.OPEN, TITLE, "no block"), id="no-block"
            ),
        ],
    )
    def test_the_gate_refuses_an_item_that_is_not_a_writable_issue(
        self, storage: body.Storage, reference: forge.ItemReference, clone: Path
    ) -> None:
        context, client = world(storage, item_with(card()), clone)
        client.issue_references[90] = reference
        with pytest.raises(decide.InvalidTargetError):
            decide.fresh_item(context, 90)
        assert client.body_writes == []


def test_the_gate_reads_the_item_once(clone: Path) -> None:
    context, client = world(body.Storage.GITHUB, item_with(card()), clone)
    decide.fresh_item(context, 90)
    assert client.issue_reference_lookups == [90]
