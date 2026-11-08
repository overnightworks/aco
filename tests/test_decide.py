"""The shared ruling writer (`specs/rule.spec.md`) on a fake forge, on both storage pins."""

import fcntl
import re
import threading
from dataclasses import replace
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


def option_rulings(lines: tuple[expectations.ExpectationLine, ...]) -> list[str | None]:
    """The ruling of each option line of `lines`, in order."""
    return [line.ruling for line in lines if isinstance(line, expectations.OptionLine)]


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
        committed = decide.rule(
            context, decide.fresh_item(context, 90, command="rule"), [choose(2)], TODAY
        )
        written = client.item_bodies[90]
        assert committed.lines == tuple(expectations.expectation_lines(written, storage=storage))
        assert option_rulings(committed.lines) == [None, "A"]

    def test_committed_carries_the_title_of_the_item_the_gate_read(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card()), clone)
        committed = decide.rule(
            context, decide.fresh_item(context, 90, command="rule"), [choose(1)], TODAY
        )
        assert (committed.number, committed.title) == (90, TITLE)

    def test_committed_counts_the_lines_still_open(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, _ = world(storage, item_with(card(), card(), card()), clone)
        committed = decide.rule(
            context, decide.fresh_item(context, 90, command="rule"), [choose(2)], TODAY
        )
        assert committed.open_remaining == 2

    def test_two_named_lines_land_in_one_write(self, storage: body.Storage, clone: Path) -> None:
        context, client = world(storage, item_with(card(), card()), clone)
        committed = decide.rule(
            context, decide.fresh_item(context, 90, command="rule"), [choose(1), choose(2)], TODAY
        )
        assert len(client.body_writes) == 1
        assert option_rulings(committed.lines) == ["A", "A"]

    def test_withdraw_writes_every_named_line_once_and_counts_the_rest(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), card(), card()), clone)
        fresh = decide.fresh_item(context, 90, command="withdraw")
        committed = decide.withdraw(context, fresh, [1, 3], TODAY)
        written = client.item_bodies[90]
        forms = [line.form for line in committed.lines]
        withdrawn, options = expectations.LineForm.WITHDRAWN, expectations.LineForm.OPTIONS
        assert len(client.body_writes) == 1
        assert committed.lines == tuple(expectations.expectation_lines(written, storage=storage))
        assert (forms, committed.open_remaining) == ([withdrawn, options, withdrawn], 1)

    def test_withdraw_refusing_a_later_line_writes_nothing(
        self, storage: body.Storage, clone: Path
    ) -> None:
        context, client = world(storage, item_with(card(), ruled_card()), clone)
        fresh = decide.fresh_item(context, 90, command="withdraw")
        with pytest.raises(expectations.ExpectationAlreadyRuledError):
            decide.withdraw(context, fresh, [1, 2], TODAY)
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
        clone: Path,
    ) -> None:
        context, client = world(storage, item_body, clone)
        fresh = decide.fresh_item(context, 90, command="rule")
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
            decide.fresh_item(context, 90, command="rule")
        assert client.body_writes == []


def test_the_gate_names_the_command_it_guards(clone: Path) -> None:
    context, client = world(body.Storage.GITHUB, item_with(card()), clone)
    client.issue_references[90] = forge.ItemReference(
        forge.ItemState.OPEN, TITLE, "no block", is_landing=True
    )
    with pytest.raises(decide.InvalidTargetError) as refused:
        decide.fresh_item(context, 90, command="withdraw")
    assert str(refused.value) == "#90 is a pull request, not an issue; withdraw needs an issue"


def test_a_failed_item_read_stays_a_forge_failure(clone: Path) -> None:
    """Spec: RULE-11, WITHDRAW-13 -- a forge failure is `unavailable`, never a bad target."""
    context, client = world(body.Storage.GITHUB, item_with(card()), clone)
    client.scripted_item_reads.append(forge.ForgeError("item read failed"))
    with pytest.raises(forge.ForgeError) as failed:
        decide.fresh_item(context, 90, command="rule")
    assert not isinstance(failed.value, decide.InvalidTargetError)


def test_the_gate_reads_the_item_once(clone: Path) -> None:
    context, client = world(body.Storage.GITHUB, item_with(card()), clone)
    decide.fresh_item(context, 90, command="rule")
    assert client.issue_reference_lookups == [90]


def lock_environment(tmp_path: Path) -> dict[str, str]:
    return {"XDG_STATE_HOME": str(tmp_path / "state")}


def item_locks(tmp_path: Path) -> list[str]:
    directory = tmp_path / "state" / "aco" / "item-locks"
    return sorted(path.name for path in directory.iterdir())


class LockWitnessForge(FakeForge):
    """Records, at every read of an item, whether the item's lock file is held by
    another open file description: a read made under the per-item turn finds it
    held, so no second writer can read the item before the first one has written;
    the same holds at every write.
    A read answers the body last written, as a real forge does."""

    def __init__(self, reference: forge.ItemReference, lock_directory: Path) -> None:
        super().__init__(issue_references={90: reference})
        self.lock_directory = lock_directory
        self.lock_held_at_reads: list[bool] = []
        self.lock_held_at_writes: list[bool] = []

    def item_reference(self, number: int) -> forge.ItemReference:
        reference = super().item_reference(number)
        if number in self.item_bodies:
            reference = replace(reference, body=self.item_bodies[number])
        self.lock_held_at_reads.append(self._lock_is_held())
        return reference

    def update_item_body(self, number: int, body: str) -> None:
        self.lock_held_at_writes.append(self._lock_is_held())
        super().update_item_body(number, body)

    def _lock_is_held(self) -> bool:
        if not self.lock_directory.is_dir():
            return False
        locks = list(self.lock_directory.iterdir())
        return len(locks) == 1 and _held_by_another(locks[0])


def _held_by_another(lock: Path) -> bool:
    with lock.open("rb") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


class TestTurn:
    def test_two_writers_of_distinct_lines_of_one_item_both_land(
        self, github_clone: Path, tmp_path: Path
    ) -> None:
        """Spec: RULE-40, WITHDRAW-15, ABRD-113 -- writers of one item are serialized."""
        track_board_config(github_clone, 'storage = "github"\n')
        reference = forge.ItemReference(forge.ItemState.OPEN, TITLE, item_with(card(), card()))
        client = LockWitnessForge(reference, tmp_path / "state" / "aco" / "item-locks")
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
                    decide.rule(context, fresh, [choose(line)], TODAY)
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
        assert (str(blocker / "aco" / "item-locks") in str(refused.value), client.body_writes) == (
            True,
            [],
        )
        assert (client.issue_reference_lookups, forges_built) == ([], [])
