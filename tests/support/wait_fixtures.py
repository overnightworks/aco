"""The time and the forge a test of `aco wait` controls: a clock only the pause
moves, with what happens after chosen pauses, and a forge that reflects its own
writes the way a real one does."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest
from github_fixtures import FakeForge, serve_forge

from aco import cmd_wait, forge

MAXIMUM_PAUSES = 1000
ITEM = 7


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


def serve_item(monkeypatch: pytest.MonkeyPatch, reference: forge.ItemReference) -> FakeForge:
    """A forge whose item 7 is `reference`."""
    return serve_forge(monkeypatch, FakeForge(issue_references={ITEM: reference}))


def reflect_the_written_body(client: FakeForge) -> None:
    """Makes the next read of item 7 answer the body last written to it."""
    client.issue_references[ITEM] = replace(
        client.issue_references[ITEM], body=client.item_bodies[ITEM]
    )


def install(monkeypatch: pytest.MonkeyPatch, client: FakeForge) -> Ticks:
    """Replaces the command's pause and clock by a `Ticks` counting `client`'s item reads."""
    ticks = Ticks(reads=lambda: len(client.issue_reference_lookups))
    monkeypatch.setattr(cmd_wait, "pause_between_checks", ticks.pause)
    monkeypatch.setattr(cmd_wait, "clock", ticks.clock)
    return ticks
