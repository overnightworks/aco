"""The board's address: the one place that builds the URL `aco serve` prints,
`aco board --url` prints and the `ask` and `step` tools of `aco mcp` return.

The token and the optional selection ride in the fragment, which a browser
never sends back to the server, so the shell at `PAGE_PATH` needs no token to
answer it (`specs/serve.spec.md` ABRD-10).
"""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from . import protocol, repositories
from .board_token import (
    MalformedTokenFileError,
    MissingTokenFileError,
    UnreadableTokenFileError,
    existing_board_token,
    token_path,
)

LOOPBACK_HOST = "127.0.0.1"
PAGE_PATH = "/"
TOKEN_FIELD = "t"  # noqa: S105 - names the fragment field that carries the token and holds no secret
CARD_FIELD = "c"
STEP_FIELD = "s"


@dataclass(frozen=True)
class CardLink:
    """One card of item `item` of `repository` (`owner/repo`), named by its `line`."""

    repository: str
    item: int
    line: int


@dataclass(frozen=True)
class StepLink:
    """The step waiting on item `item` of `repository` (`owner/repo`)."""

    repository: str
    item: int


def board_url(port: int, token: str, selection: CardLink | StepLink | None = None) -> str:
    """`http://127.0.0.1:<port>/#t=<token>`, with the card or step to open appended."""
    fragment = f"{TOKEN_FIELD}={token}"
    if isinstance(selection, CardLink):
        reference = f"{selection.repository}/{selection.item}/{selection.line}"
        fragment += f"&{CARD_FIELD}={quote(reference, safe='/')}"
    elif isinstance(selection, StepLink):
        reference = f"{selection.repository}/{selection.item}"
        fragment += f"&{STEP_FIELD}={quote(reference, safe='/')}"
    # S5332: loopback only, no TLS by design (README.md, `aco serve`)
    return (
        f"http://{LOOPBACK_HOST}:{port}{PAGE_PATH}#{fragment}"  # NOSONAR(S5332) loopback-only URL
    )


def configured_board_url(selection: CardLink | StepLink | None = None) -> str:
    """The URL of the board the configuration names: the port from `board_port`
    and the token from the token file, which a board start wrote. Refused by
    name when either is missing."""
    environment, home = os.environ, Path.home()
    config = repositories.config_path(environment, home)
    port = repositories.configured_board_port(config)
    if port is None:
        raise protocol.ClaimError(f"board_port is not set in {config}")
    try:
        token = existing_board_token(token_path(environment, home))
    except (MalformedTokenFileError, MissingTokenFileError, UnreadableTokenFileError) as error:
        raise protocol.ClaimError(str(error)) from error
    return board_url(port, token, selection)


def configured_board_url_or_none(selection: CardLink | StepLink | None = None) -> str | None:
    """`configured_board_url`, or `None` where the configuration cannot give one."""
    try:
        return configured_board_url(selection)
    except protocol.ClaimError:
        return None
