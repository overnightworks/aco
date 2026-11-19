"""The time and the forge a test of `aco wait` controls: a clock only the pause
moves, with what happens after chosen pauses, and a forge read once per command."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from board_fixtures import board_issue, complete_contract, holding_for_the_operator
from cli_fixtures import freeze_cli_now
from github_fixtures import FakeForge, serve_forge
from option_cards import group_body

from aco import cmd_wait, forge, github, workboard

MAXIMUM_PAUSES = 2000
ITEM = 7
OTHER_ITEM = 50


@dataclass
class Ticks:
    """A pause that moves a fake clock instead of sleeping. `afterwards` maps a
    pause number (the first is 1) to what happens once it has passed, and
    `reads_seen` is how many forge reads had been made when each pause began."""

    reads: Callable[[], int]
    afterwards: dict[int, Callable[[], None]] = field(default_factory=dict)
    now: float = 0.0
    pauses: list[float] = field(default_factory=list)
    reads_seen: list[int] = field(default_factory=list)

    def pause(self, seconds: float) -> None:
        assert len(self.pauses) < MAXIMUM_PAUSES, "the command never ended"
        self.reads_seen.append(self.reads())
        self.pauses.append(seconds)
        self.now += seconds
        self.afterwards.get(len(self.pauses), lambda: None)()

    def clock(self) -> float:
        return self.now


@dataclass
class SnapshotForge(FakeForge):
    """A forge that answers the references as they stood when it was built, the
    way a state ref read once per command does; a body written to it lands in
    `shared`, where the next forge built finds it."""

    shared: dict[int, forge.ItemReference] = field(default_factory=dict)

    def update_item_body(self, number: int, body: str, *, replacing: str) -> None:
        super().update_item_body(number, body, replacing=replacing)
        self.shared[number] = replace(self.shared[number], body=body)


@dataclass
class SnapshotWorld:
    """Item 7 as the store holds it, and every forge a command built over it."""

    references: dict[int, forge.ItemReference]
    built: list[SnapshotForge] = field(default_factory=list)

    def reads(self) -> int:
        return sum(len(client.issue_reference_lookups) for client in self.built)


def serve_item(monkeypatch: pytest.MonkeyPatch, reference: forge.ItemReference) -> FakeForge:
    """One forge, shared by every command, whose item 7 is `reference`."""
    return serve_forge(monkeypatch, FakeForge(issue_references={ITEM: reference}))


def serve_snapshots(
    monkeypatch: pytest.MonkeyPatch, reference: forge.ItemReference
) -> SnapshotWorld:
    """GitHub's forge as a store each command reads once: item 7 starts as `reference`."""
    world = SnapshotWorld({ITEM: reference})

    def build(_repository: forge.RepositoryId) -> SnapshotForge:
        client = SnapshotForge(issue_references=dict(world.references), shared=world.references)
        world.built.append(client)
        return client

    monkeypatch.setattr(github, "GitHubForge", build)
    return world


def reads_of(client: FakeForge) -> Callable[[], int]:
    return lambda: len(client.issue_reference_lookups)


def install(monkeypatch: pytest.MonkeyPatch, reads: Callable[[], int]) -> Ticks:
    """Replaces the command's pause and clock by a `Ticks` that counts forge `reads`."""
    ticks = Ticks(reads=reads)
    monkeypatch.setattr(cmd_wait, "pause_between_checks", ticks.pause)
    monkeypatch.setattr(cmd_wait, "clock", ticks.clock)
    return ticks


def open_reference(raw: str, *, is_landing: bool = False) -> forge.ItemReference:
    return forge.ItemReference(forge.ItemState.OPEN, "Karte", raw, is_landing)


def card_issue(raw: str) -> workboard.Issue:
    """Item 7 holding open cards in a body that waits on the operator."""
    return board_issue(ITEM, "Karte", raw)


def waiting_card() -> workboard.Issue:
    return card_issue(holding_for_the_operator(group_body()))


def free_item() -> workboard.Issue:
    return board_issue(OTHER_ITEM, "Alpha", complete_contract(f"Claim #{OTHER_ITEM}."))


@pytest.fixture
def frozen_wait_world(monkeypatch: pytest.MonkeyPatch, github_world: Path) -> None:
    freeze_cli_now(monkeypatch)
