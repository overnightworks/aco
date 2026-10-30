"""Vulture whitelist.

`NoItemKind.DOCS` and `NoItemKind.FIX` are never referenced by a literal
attribute access; the code reaches them only by dynamic construction
(`NoItemKind(value)`) and iteration (`for kind in NoItemKind`), both invisible
to vulture's static analysis. Naming them here is the whole fix -- this file
is never imported by the package itself.

`_BoardApiRequestHandler.do_GET`/`do_POST`/`log_message` are
`http.server`'s own dispatch and logging surface: `handle_one_request` calls
`do_GET`/`do_POST` by `getattr(self, "do_" + self.command)`, and every stdlib
logging call reaches the override through `BaseHTTPRequestHandler`'s own
`self.log_message(...)` -- never by a literal call this package writes, so
vulture never sees a caller for any of the three.

`argparse.Action.nargs`/`const`/`default`/`metavar` stand for the `_ArgumentOptions`
keys that `add_argument` receives through `**options`: vulture matches by
attribute name, and argparse stores each of those keywords as the `Action`
attribute of the same name, so the names are used.

`Size.MEDIUM` and `Size.LARGE` are built only dynamically (`Size(value)`,
iteration over `Size`), and `SizeClassStats.p80_hours` is read only through
`asdict` when `board_payload` serializes the `--json` output; vulture sees
no literal access for any of the three.

`BoardItem.priority_bucket`/`age_days` and `Board.stale` are part of `board_payload`'s
own `--json` contract (`asdict` serializes every dataclass field whether or
not any function reads it back by name), and tests already pin all three by
name (`tests/test_board.py`'s `priority_bucket`/`stale` attribute
assertions, `tests/test_cli.py`'s `"age_days"` envelope pin).
`BoardItem.claim_age`, `SizeClassMeasurement.first_event_at`/`last_event_at`,
and `Measurements.unfinished`/`as_of` are likewise part of
`board_payload`'s own `--json` contract, exercised by
`tests/test_cli.py`'s `"claim_age"` envelope pin and
`tests/test_board.py`'s own `measurements`/`classes` payload assertions.

`MergeMethod.REBASE` is reached the same way as
`NoItemKind.DOCS`: `GitHubForge.allowed_merge_methods` iterates `MergeMethod`
to read each of GitHub's merge settings, and no code names the one method
`aco land` never merges with.

`aco.board.server._BoardRequestHandler.send_error` and its
`close_connection` and `request_version` assignments are
`http.server`'s own hooks: the stdlib calls `self.send_error(...)` for a
request it cannot parse, its `handle` loop reads `self.close_connection` to
end the connection, and `send_response` reads `self.request_version` to
decide whether to write headers -- none through a call or read this package
writes.

The `DecisionKind` members are reached only by construction from a stored
value (`DecisionKind(value)`) and by iteration when the grammar lists the
accepted kinds; no code names one of them. `RulingVia.BOARD` and
`RulingVia.CHAT` are reached the same way, from `--via` and from a stored
`via`; so are the board's own `RulingVia.BOARD`, `RulingVia.CHAT` and
`RulingVia.DEFAULT`, reached only by construction from the `via` aco stored. The board's
`Outcome.YES`, `Outcome.NO` and `Outcome.LATER` are reached only by
construction from the ruling of a stored yes/no line, which the board shows
and never writes.
"""

import argparse
from datetime import UTC, date, datetime

from aco.board.ports import Outcome as BoardOutcome
from aco.board.ports import RulingVia as BoardRulingVia
from aco.board.server import _BoardRequestHandler as _BoardApiRequestHandler
from aco.expectation_grammar import DecisionKind, RulingVia
from aco.metrics import Size, SizeClassStats
from aco.workboard import (
    Board,
    BoardItem,
    BodyReadState,
    Contract,
    ExpectationProgress,
    ExpectationState,
    Measurements,
    MergeMethod,
    NoItemKind,
    SizeClassMeasurement,
    Stage,
)

_size_class_stats_for_vulture = SizeClassStats(
    size=Size.SMALL, n=0, median_hours=0.0, p80_hours=0.0, weak=False
)
_size_class_measurement_for_vulture = SizeClassMeasurement(
    stats=_size_class_stats_for_vulture,
    first_event_at=datetime(2000, 1, 1, tzinfo=UTC),
    last_event_at=datetime(2000, 1, 1, tzinfo=UTC),
)
_board_item_for_vulture = BoardItem(
    number=0,
    title="",
    labels=(),
    kind=None,
    priority_category=0,
    priority_bucket="",
    priority_order=0,
    container=None,
    container_parent=None,
    scope=None,
    whole=None,
    contract=Contract(now=None, next=None, done_when=None),
    next_step=None,
    contract_complete=False,
    idea=False,
    expectation_state=ExpectationState.NONE,
    expectation_progress=ExpectationProgress(open=0, total=0),
    ruling_landings=None,
    ruling_old=None,
    frozen_trigger=None,
    open_blockers=(),
    freed_on=None,
    freed_days=None,
    stage=Stage.TEXT_ONLY,
    age_days=0,
    idle_days=0,
    active_claim=None,
    claim_age=None,
    claim_old=False,
    unblocks_count=0,
    score=0,
    actionable=False,
    actionable_reason=None,
    waits_on_operator=False,
    terminal_actionable_reason=None,
    read_state=BodyReadState.VALID,
    childless_verdict=None,
    size=None,
    has_slices=False,
    estimate=None,
)
_board_for_vulture = Board(
    items=(),
    ready_now=(),
    stale=(),
    recovery=(),
    landings=(),
    uncut=(),
    repository="",
    requests=0,
    measurements=Measurements(
        classes=(), unfinished=0, unparsed=0, since=None, as_of=date(2000, 1, 1)
    ),
)

_referenced_only_for_vulture = (
    NoItemKind.DOCS,
    NoItemKind.FIX,
    MergeMethod.REBASE,
    DecisionKind.PRODUCT,
    DecisionKind.TECHNICAL,
    DecisionKind.DATA_RISK,
    DecisionKind.MONEY,
    DecisionKind.ACCESS,
    DecisionKind.WORDING,
    RulingVia.BOARD,
    RulingVia.CHAT,
    BoardRulingVia.BOARD,
    BoardRulingVia.CHAT,
    BoardRulingVia.DEFAULT,
    BoardOutcome.YES,
    BoardOutcome.NO,
    BoardOutcome.LATER,
    _BoardApiRequestHandler.do_GET,
    _BoardApiRequestHandler.do_POST,
    _BoardApiRequestHandler.log_message,
    _BoardApiRequestHandler.send_error,
    _BoardApiRequestHandler.close_connection,
    _BoardApiRequestHandler.request_version,
    Size.MEDIUM,
    Size.LARGE,
    _size_class_stats_for_vulture.p80_hours,
    _board_item_for_vulture.priority_bucket,
    _board_item_for_vulture.age_days,
    _board_item_for_vulture.claim_age,
    _board_item_for_vulture.freed_days,
    _board_for_vulture.stale,
    _board_for_vulture.measurements.unfinished,
    _board_for_vulture.measurements.as_of,
    _size_class_measurement_for_vulture.first_event_at,
    _size_class_measurement_for_vulture.last_event_at,
    argparse.Action.nargs,
    argparse.Action.const,
    argparse.Action.default,
    argparse.Action.metavar,
)
