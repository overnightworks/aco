"""What a failed `gh` call means: the one owner of its classification."""

import re

from . import forge

# For `HTTP 5xx`, gh's combined output names the status
# code but never its class, so any 5xx is matched by digit rather than by an
# enumerated list of codes that would need to grow with the API.
HTTP_SERVER_ERROR_PATTERN = re.compile(r"HTTP 5\d\d")
# gh words a DNS failure `error connecting to <host>` and any other connect failure `dial tcp`.
_TRANSIENT_PATTERN = re.compile(
    HTTP_SERVER_ERROR_PATTERN.pattern + r"|connection reset|timeout|error connecting to|dial tcp"
)


def nonzero_exit_failure(decoded: str, return_code: int, purpose: str) -> forge.ForgeError:
    """Classify a nonzero `gh` exit from its decoded combined output.

    `gh`'s own exit code never carries the HTTP status, so this reads the
    same prose a human would; the fallback stays an unclassified `ForgeError`
    rather than guessing at retry safety.
    """
    if "HTTP 404" in decoded:
        return forge.ForgeNotFoundError(decoded)
    if "HTTP 401" in decoded or "HTTP 403" in decoded:
        return forge.ForgePermissionDeniedError(decoded)
    if _TRANSIENT_PATTERN.search(decoded):
        return forge.ForgeTransientError(decoded)
    return forge.ForgeError(decoded or f"{purpose} failed with exit {return_code}")
