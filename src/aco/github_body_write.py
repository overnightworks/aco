"""Writing one item's body on GitHub and judging what a failed write tells of it."""

import json
from collections.abc import Callable
from enum import StrEnum

from . import forge
from .protocol import ClaimError

GitHubRunner = Callable[..., str]


class BodyWriteOutcome(StrEnum):
    """What a failed `update_item_body` tells of the body: `REFUSED` wrote
    nothing, `UNKNOWN` may have written it."""

    REFUSED = "refused"
    UNKNOWN = "unknown"


def body_write_outcome(error: ClaimError) -> BodyWriteOutcome:
    """The outcome of a body write that raised `error`: the forge's own
    refusal of the call (authorization, no such item), and a `gh` that never
    ran (a plain `ClaimError` -- `_bounded_command` raises only typed forge
    errors once the process has started) wrote nothing; any other forge
    failure may have come after the write."""
    refused = isinstance(
        error, forge.ForgePermissionDeniedError | forge.ForgeNotFoundError
    ) or not isinstance(error, forge.ForgeError)
    return BodyWriteOutcome.REFUSED if refused else BodyWriteOutcome.UNKNOWN


def patch_item_body(
    run: GitHubRunner, repository: forge.RepositoryId, number: int, body: str
) -> None:
    """Send `body` as issue `number`'s body through the caller's `run`."""
    path = f"repos/{repository}/issues/{number}"
    run(
        ["api", "--method", "PATCH", path, "--input", "-"],
        input_data=json.dumps({"body": body}).encode("utf-8"),
    )
