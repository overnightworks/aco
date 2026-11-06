"""Vulture whitelist.

`NoItemKind.DOCS` is never referenced by a literal attribute access; the code
reaches it only by dynamic construction (`NoItemKind(value)`) and iteration
(`for kind in NoItemKind`), both invisible to vulture's static analysis.
Naming it here is the whole fix -- this file is never imported by the package
itself.

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

`Size.SMALL`, `Size.MEDIUM` and `Size.LARGE` are built only dynamically (`Size(value)`,
iteration over `Size`); vulture sees no literal access for any of the three.

`BoardItem.priority_bucket`/`age_days`/`freed_days` are part of `board_payload`'s
own `--json` contract (`asdict` serializes every dataclass field whether or
not any function reads it back by name), and tests already pin them by
name (`tests/test_board.py`'s `priority_bucket` attribute assertions,
`tests/test_cli.py`'s `"age_days"` envelope pin).

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
accepted kinds; no code names one of them. `RulingVia.CHAT` is reached the
same way, from `--via` and from a stored `via`.
"""

import argparse

from aco.board.server import _BoardRequestHandler as _BoardApiRequestHandler
from aco.body import Size
from aco.expectation_grammar import DecisionKind, RulingVia
from aco.workboard import (
    BoardItem,
    BodyReadState,
    Contract,
    ExpectationProgress,
    ExpectationState,
    MergeMethod,
    NoItemKind,
    Stage,
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
)

_referenced_only_for_vulture = (
    NoItemKind.DOCS,
    MergeMethod.REBASE,
    DecisionKind.PRODUCT,
    DecisionKind.TECHNICAL,
    DecisionKind.DATA_RISK,
    DecisionKind.MONEY,
    DecisionKind.ACCESS,
    DecisionKind.WORDING,
    RulingVia.CHAT,
    _BoardApiRequestHandler.do_GET,
    _BoardApiRequestHandler.do_POST,
    _BoardApiRequestHandler.log_message,
    _BoardApiRequestHandler.send_error,
    _BoardApiRequestHandler.close_connection,
    _BoardApiRequestHandler.request_version,
    Size.SMALL,
    Size.MEDIUM,
    Size.LARGE,
    _board_item_for_vulture.priority_bucket,
    _board_item_for_vulture.age_days,
    _board_item_for_vulture.freed_days,
    argparse.Action.nargs,
    argparse.Action.const,
    argparse.Action.default,
    argparse.Action.metavar,
)
