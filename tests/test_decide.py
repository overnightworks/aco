"""The shared ruling writer (`specs/rule.spec.md`) on a fake forge, on both storage pins."""

import os
import re
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body
from board_forge import item_signals
from cli_fixtures import run_context_over, track_board_config
from github_fixtures import FakeForge
from item_lock_witness import LockWitnessForge
from option_cards import GOLDEN_CARD_HASH, SECOND_CARD, ask_card, card, card_head, ruled_card

from aco import body, body_fence, decide, expectations, forge, protocol, repositories
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


def option_rulings(lines: tuple[expectations.ExpectationLine, ...]) -> list[str | None]:
    """The ruling of each option line of `lines`, in order."""
    return [line.ruling for line in lines if isinstance(line, expectations.OptionLine)]


def world(
    storage: body.Storage, item_body: str, github_clone: Path
) -> tuple[RunContext, FakeForge]:
    """A checkout pinned to `storage` whose issue 90 is `item_body`, behind a fake forge."""
    track_board_config(github_clone, f'storage = "{storage.value}"\n')
    reference = forge.ItemReference(forge.ItemState.OPEN, TITLE, item_body)
    client = FakeForge(issue_references={90: reference})
    return run_context_over(client), client


def write_ruling(
    context: RunContext, fresh: decide.FreshItem, named: list[decide.LineOutcome]
) -> decide.Committed:
    """The ruling write, its signal landing in this test's own state directory."""
    return decide.rule(
        context, fresh, named, TODAY, state=repositories.state_directory(os.environ, Path.home())
    )


def write_withdrawal(
    context: RunContext, fresh: decide.FreshItem, indexes: list[int]
) -> decide.Committed:
    """The withdrawal write, its signal landing in this test's own state directory."""
    return decide.withdraw(
        context, fresh, indexes, TODAY, state=repositories.state_directory(os.environ, Path.home())
    )


@pytest.mark.parametrize("storage", STORAGE_PINS)
class TestCommitted:
    def test_committed_lines_are_the_expectation_lines_of_the_written_body(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), card()), github_clone)
        committed = write_ruling(
            context, decide.fresh_item(context, 90, command="rule"), [choose(2)]
        )
        written = client.item_bodies[90]
        assert committed.lines == tuple(expectations.expectation_lines(written, storage=storage))
        assert option_rulings(committed.lines) == [None, "A"]

    def test_committed_carries_the_title_of_the_item_the_gate_read(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card()), github_clone)
        committed = write_ruling(
            context, decide.fresh_item(context, 90, command="rule"), [choose(1)]
        )
        assert (committed.number, committed.title) == (90, TITLE)

    def test_committed_counts_the_lines_still_open(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card(), card(), card()), github_clone)
        committed = write_ruling(
            context, decide.fresh_item(context, 90, command="rule"), [choose(2)]
        )
        assert committed.open_remaining == 2

    def test_two_named_lines_land_in_one_write(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), card()), github_clone)
        committed = write_ruling(
            context, decide.fresh_item(context, 90, command="rule"), [choose(1), choose(2)]
        )
        assert len(client.body_writes) == 1
        assert option_rulings(committed.lines) == ["A", "A"]

    def test_withdraw_writes_every_named_line_once_and_counts_the_rest(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), card(), card()), github_clone)
        fresh = decide.fresh_item(context, 90, command="withdraw")
        committed = write_withdrawal(context, fresh, [1, 3])
        written = client.item_bodies[90]
        forms = [line.form for line in committed.lines]
        withdrawn, options = expectations.LineForm.WITHDRAWN, expectations.LineForm.OPTIONS
        assert len(client.body_writes) == 1
        assert committed.lines == tuple(expectations.expectation_lines(written, storage=storage))
        assert (forms, committed.open_remaining) == ([withdrawn, options, withdrawn], 1)

    def test_withdraw_refusing_a_later_line_writes_nothing(
        self, storage: body.Storage, github_clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), ruled_card()), github_clone)
        fresh = decide.fresh_item(context, 90, command="withdraw")
        with pytest.raises(expectations.ExpectationAlreadyRuledError):
            write_withdrawal(context, fresh, [1, 2])
        assert client.body_writes == []

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
        github_clone: Path,
    ) -> None:
        context, client = world(storage, item_body, github_clone)
        fresh = decide.fresh_item(context, 90, command="rule")
        with pytest.raises(refusal):
            write_ruling(context, fresh, named)
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
        self, storage: body.Storage, reference: forge.ItemReference, github_clone: Path
    ) -> None:
        context, client = world(storage, item_with(card()), github_clone)
        client.issue_references[90] = reference
        with pytest.raises(decide.InvalidTargetError):
            decide.fresh_item(context, 90, command="rule")
        assert client.body_writes == []


def test_the_gate_names_the_command_it_guards(github_clone: Path) -> None:
    context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
    client.issue_references[90] = forge.ItemReference(
        forge.ItemState.OPEN, TITLE, "no block", is_landing=True
    )
    with pytest.raises(decide.InvalidTargetError) as refused:
        decide.fresh_item(context, 90, command="withdraw")
    assert str(refused.value) == "#90 is a pull request, not an issue; withdraw needs an issue"


def test_a_failed_item_read_stays_a_forge_failure(github_clone: Path) -> None:
    """Spec: RULE-11, WITHDRAW-13 -- a forge failure is `unavailable`, never a bad target."""
    context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
    client.scripted_item_reads.append(forge.ForgeError("item read failed"))
    with pytest.raises(forge.ForgeError) as failed:
        decide.fresh_item(context, 90, command="rule")
    assert not isinstance(failed.value, decide.InvalidTargetError)


def test_the_gate_reads_the_item_once(github_clone: Path) -> None:
    context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
    decide.fresh_item(context, 90, command="rule")
    assert client.issue_reference_lookups == [90]


def lock_environment(tmp_path: Path) -> dict[str, str]:
    return {"XDG_STATE_HOME": str(tmp_path / "state")}


def item_locks(tmp_path: Path) -> list[str]:
    directory = tmp_path / "state" / "aco" / "item-locks"
    return sorted(path.name for path in directory.iterdir())


class TestTurn:
    def test_two_writers_of_distinct_lines_of_one_item_both_land(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: RULE-40, WITHDRAW-15, ABRD-113 -- writers of one item are serialized."""
        track_board_config(github_clone, 'storage = "github"\n')
        reference = forge.ItemReference(forge.ItemState.OPEN, TITLE, item_with(card(), card()))
        client = LockWitnessForge(
            tmp_path / "state" / "aco" / "item-locks", issue_references={90: reference}
        )
        failures: list[BaseException] = []

        def write(line: int) -> None:
            context = run_context_over(client)
            try:
                with decide.turn(
                    context,
                    90,
                    command="rule",
                    environment=lock_environment(tmp_path),
                    home=tmp_path,
                ) as fresh:
                    decide.rule(
                        context,
                        fresh,
                        [choose(line)],
                        TODAY,
                        state=repositories.state_directory(lock_environment(tmp_path), tmp_path),
                    )
            except BaseException as failure:
                failures.append(failure)

        writers = [threading.Thread(target=write, args=(line,)) for line in (1, 2)]
        for writer in writers:
            writer.start()
        for writer in writers:
            writer.join(timeout=10)
        assert failures == []
        lines = tuple(
            expectations.expectation_lines(client.item_bodies[90], storage=body.Storage.GITHUB)
        )
        assert option_rulings(lines) == ["A", "A"]
        assert client.lock_held_at_reads == [True, True]
        assert client.lock_held_at_writes == [True, True]

    def test_the_lock_is_one_digest_named_file_per_item_in_one_flat_directory(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
        client.issue_references[91] = client.issue_references[90]
        for number in (90, 91, 90):
            with decide.turn(
                context,
                number,
                command="rule",
                environment=lock_environment(tmp_path),
                home=tmp_path,
            ):
                pass
        names = item_locks(tmp_path)
        assert len(names) == 2
        assert all(re.fullmatch(r"[0-9a-f]{64}", name) for name in names)

    def test_an_unwritable_lock_directory_refuses_naming_the_path_and_reads_nothing(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: RULE-41, WITHDRAW-16 -- no lock, so nothing is read or written."""
        _, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
        forges_built: list[RunContext] = []
        context = RunContext(None, build_forge=lambda built: forges_built.append(built) or client)
        blocker = tmp_path / "blocker"
        blocker.write_text("a file, not a directory", encoding="utf-8")
        environment = {"XDG_STATE_HOME": str(blocker)}
        turn = decide.turn(context, 90, command="rule", environment=environment, home=tmp_path)
        with pytest.raises(decide.ItemLockUnavailableError) as refused:
            turn.__enter__()
        assert (
            str(refused.value).count(str(blocker / "aco" / "item-locks")),
            client.body_writes,
        ) == (
            1,
            [],
        )
        assert (client.issue_reference_lookups, forges_built) == ([], [])


class TestWriteItemBody:
    def test_a_body_equal_to_the_one_it_replaces_makes_no_forge_call(self) -> None:
        client = FakeForge()

        written = decide.write_item_body(client, 90, "same text", replacing="same text")

        assert written is False
        assert client.body_writes == []

    def test_another_body_is_written_and_the_port_gets_the_text_it_replaces(self) -> None:
        replaced: list[str] = []

        class RecordingForge(FakeForge):
            def update_item_body(self, number: int, body: str, *, replacing: str) -> None:
                replaced.append(replacing)
                super().update_item_body(number, body, replacing=replacing)

        client = RecordingForge()

        written = decide.write_item_body(client, 90, "new text", replacing="old text")

        assert (written, client.body_writes, replaced) == (True, [(90, "new text")], ["old text"])


def test_ruling_a_line_whose_hand_written_picture_holds_a_fence_line_keeps_the_body_whole(
    github_clone: Path,
) -> None:
    written_picture = card_head().split("picture = ")[1].split("\ncaption")[0]
    hand_written = card().replace(written_picture, '"<svg/>\\n```\\nx"', 1)
    given = item_with(hand_written)
    shown = [
        line
        for line in expectations.expectation_lines(given, storage=body.Storage.GITHUB)
        if isinstance(line, expectations.OptionLine)
    ]
    context, client = world(body.Storage.GITHUB, given, github_clone)

    write_ruling(
        context,
        decide.fresh_item(context, 90, command="rule"),
        [choose(1, shown[0].card_hash)],
    )

    written = client.item_bodies[90]
    stored = [
        line.picture
        for line in expectations.expectation_lines(written, storage=body.Storage.GITHUB)
        if isinstance(line, expectations.OptionLine)
    ]
    body.locate_block(written)
    assert len(body_fence.walk_fences(written).fences) == 1
    assert stored == ["<svg/>\n```\nx"]


type Write = Callable[[RunContext, decide.FreshItem, Path], object]


def write_in_a_turn(context: RunContext, tmp_path: Path, write: Write) -> None:
    """Runs `write` on a fresh read of item 90 under its turn, the way every command does."""
    environment = lock_environment(tmp_path)
    with decide.turn(context, 90, command="rule", environment=environment, home=tmp_path) as fresh:
        write(context, fresh, repositories.state_directory(environment, tmp_path))


def rule_line(index: int) -> Write:
    return lambda context, fresh, state: decide.rule(
        context, fresh, [choose(index)], TODAY, state=state
    )


def return_line_1(context: RunContext, fresh: decide.FreshItem, state: Path) -> object:
    outcome = expectations.HeadReturn("Was kostet B?", GOLDEN_CARD_HASH)
    return decide.rule(context, fresh, [decide.LineOutcome(1, outcome)], TODAY, state=state)


def withdraw_line_1(context: RunContext, fresh: decide.FreshItem, state: Path) -> object:
    return decide.withdraw(context, fresh, [1], TODAY, state=state)


class TestSignal:
    @pytest.mark.parametrize(
        "write",
        [
            pytest.param(rule_line(1), id="ruled"),
            pytest.param(return_line_1, id="returned"),
            pytest.param(withdraw_line_1, id="withdrawn"),
        ],
    )
    def test_a_ruled_returned_or_withdrawn_line_touches_the_signal_the_lock_is_named_by(
        self, write: Write, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: WAIT-12, RULE-44, WITHDRAW-18 -- one file per item, named as its lock."""
        context, _ = world(body.Storage.GITHUB, item_with(card()), github_clone)
        write_in_a_turn(context, tmp_path, write)
        assert item_signals(tmp_path) == item_locks(tmp_path)

    def test_a_second_write_moves_the_modification_time_of_the_signal(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: WAIT-07, WAIT-12 -- a waiting command sees the signal move."""
        context, _ = world(body.Storage.GITHUB, item_with(card(), card()), github_clone)
        write_in_a_turn(context, tmp_path, rule_line(1))
        (signal,) = (tmp_path / "state" / "aco" / "item-signals").iterdir()
        os.utime(signal, ns=(1, 1))
        write_in_a_turn(context, tmp_path, rule_line(2))
        assert signal.stat().st_mtime_ns > 1

    def test_a_refused_write_touches_no_signal(self, github_clone: Path, tmp_path: Path) -> None:
        """Spec: WAIT-12, RULE-44 -- the signal follows a verified write only."""
        context, _ = world(body.Storage.GITHUB, item_with(ruled_card()), github_clone)
        with pytest.raises(expectations.ExpectationAlreadyRuledError):
            write_in_a_turn(context, tmp_path, rule_line(1))
        assert item_signals(tmp_path) == []

    def test_a_body_write_the_forge_refuses_touches_no_signal(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: WAIT-12 -- a body write that raises is not a verified write."""
        context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
        client.fail_update_item_body = True
        with pytest.raises(protocol.ClaimError):
            write_in_a_turn(context, tmp_path, rule_line(1))
        assert item_signals(tmp_path) == []

    def test_an_ask_touches_no_signal(self, github_clone: Path, tmp_path: Path) -> None:
        """Spec: WAIT-12 -- `ask` is no ruling, return or withdrawal."""
        context, client = world(body.Storage.GITHUB, item_with(SECOND_CARD), github_clone)
        client.issue_references[90] = forge.ItemReference(
            forge.ItemState.OPEN, TITLE, item_with(SECOND_CARD), author_is_member=True
        )
        write_in_a_turn(
            context,
            tmp_path,
            lambda context, fresh, _state: decide.ask(context, fresh, ask_card()),
        )
        assert (client.body_writes != [], item_signals(tmp_path)) == (True, [])

    def test_a_signal_that_cannot_be_touched_leaves_the_ruling_standing_and_warns_once(
        self, github_clone: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: WAIT-13 -- the write stands, one warning names the signal path."""
        context, client = world(body.Storage.GITHUB, item_with(card()), github_clone)
        blocker = tmp_path / "state" / "aco" / "item-signals"
        blocker.parent.mkdir(parents=True)
        blocker.write_text("a file, not a directory", encoding="utf-8")
        write_in_a_turn(context, tmp_path, rule_line(1))
        warnings = [
            line for line in capsys.readouterr().err.splitlines() if line.startswith("WARNING")
        ]
        assert len(client.body_writes) == 1
        assert len(warnings) == 1
        assert warnings[0].startswith("WARNING: the ruling stands, but its signal at ")
        assert str(blocker) in warnings[0]
