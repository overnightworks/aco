"""What a failed `gh` call means: the one owner of its classification, a rate limit and the
reset time GitHub names for it included."""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from . import forge

# For `HTTP 5xx`, gh's combined output names the status
# code but never its class, so any 5xx is matched by digit rather than by an
# enumerated list of codes that would need to grow with the API.
HTTP_SERVER_ERROR_PATTERN = re.compile(r"HTTP 5\d\d")
# gh words a DNS failure `error connecting to <host>` and any other connect failure `dial tcp`.
_TRANSIENT_PATTERN = re.compile(
    HTTP_SERVER_ERROR_PATTERN.pattern + r"|connection reset|timeout|error connecting to|dial tcp"
)
# gh's own closing message of a rate limit. Anchored at the end of the output, with no quote
# and no line break after the phrase, so that the phrase inside a body, a diff or a JSON answer
# is never read as one.
_RATE_LIMIT_MESSAGE = re.compile(
    r"gh: (?:(?P<secondary>You have exceeded a secondary rate limit)"
    r'|API rate limit (?:already )?exceeded for )[^"\n]*\Z'
)
_TOO_MANY_REQUESTS = "(HTTP 429)"
# GitHub states a limit's reset within its window, an hour; a time further ahead is no reset.
_MAXIMUM_RESET_AHEAD = timedelta(hours=2)
_RESET_TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class RateLimit(StrEnum):
    """Which limit refused a call; the value is how the sentence names it."""

    GRAPHQL = "GraphQL"
    REST = "REST"
    SEARCH = "search"
    SECONDARY = "secondary"


class Quota(StrEnum):
    """The primary limit a `gh` call spends; the value is how a call record names it."""

    CORE = "core"
    GRAPHQL = "graphql"
    SEARCH = "search"
    UNCOUNTED = "uncounted"


_REFUSED_LIMIT = {
    Quota.CORE: RateLimit.REST,
    Quota.GRAPHQL: RateLimit.GRAPHQL,
    Quota.SEARCH: RateLimit.SEARCH,
    Quota.UNCOUNTED: RateLimit.REST,
}


def quota_of(command: list[str]) -> Quota:
    """The quota the `gh` command line spends: a GraphQL query and `repo view` spend GraphQL's,
    a search page search's, the free `rate_limit` read none, every other call REST's core."""
    if command[1:3] in (["api", "graphql"], ["repo", "view"]):
        return Quota.GRAPHQL
    if "rate_limit" in command:
        return Quota.UNCOUNTED
    if any(argument.startswith("search/") for argument in command):
        return Quota.SEARCH
    return Quota.CORE


def _sentence(limit: RateLimit, resets_at: datetime | None) -> str:
    if limit is RateLimit.SECONDARY:
        tail = "try again in a minute"
    elif resets_at is None:
        tail = "its reset time could not be read"
    else:
        tail = f"it resets at {resets_at.astimezone(UTC).strftime(_RESET_TIME_FORMAT)}"
    return f"GitHub's {limit} rate limit is reached; {tail}"


class RateLimitedError(forge.ForgeRateLimitedError):
    """A call GitHub refused under `limit`, in the sentence of `specs/output.spec.md` (OUT-13)."""

    def __init__(self, limit: RateLimit, resets_at: datetime | None = None) -> None:
        super().__init__(_sentence(limit, resets_at), resets_at)
        self.limit = limit


def _rate_limit(decoded: str, quota: Quota) -> RateLimit | None:
    """The limit `decoded` ends with: the secondary one when gh says so or when only an
    HTTP 429 is known, otherwise the limit of the quota the refused call spends."""
    closing = _RATE_LIMIT_MESSAGE.search(decoded)
    if closing is not None:
        return RateLimit.SECONDARY if closing.group("secondary") else _REFUSED_LIMIT[quota]
    return RateLimit.SECONDARY if decoded.endswith(_TOO_MANY_REQUESTS) else None


def is_rate_limited(decoded: str) -> bool:
    """Whether `decoded` ends with a refusal under any rate limit."""
    return _rate_limit(decoded, Quota.CORE) is not None


def nonzero_exit_failure(
    decoded: str,
    return_code: int,
    purpose: str,
    *,
    quota: Quota = Quota.CORE,
) -> forge.ForgeError:
    """Classify a nonzero `gh` exit from its decoded combined output.

    `gh`'s own exit code never carries the HTTP status, so this reads the
    same prose a human would; the fallback stays an unclassified `ForgeError`
    rather than guessing at retry safety. A rate limit is told first: gh words one
    as a 403 or a 429 too. `quota` is the one the call that failed spends.
    """
    limit = _rate_limit(decoded, quota)
    if limit is not None:
        return RateLimitedError(limit)
    if "HTTP 404" in decoded:
        return forge.ForgeNotFoundError(decoded)
    if "HTTP 401" in decoded or "HTTP 403" in decoded:
        return forge.ForgePermissionDeniedError(decoded)
    if _TRANSIENT_PATTERN.search(decoded):
        return forge.ForgeTransientError(decoded)
    return forge.ForgeError(decoded or f"{purpose} failed with exit {return_code}")


def _within_the_window(reset: datetime, read_at: datetime) -> datetime | None:
    return reset if reset <= read_at + _MAXIMUM_RESET_AHEAD else None


def rest_reset(answer: str, read_at: datetime) -> datetime | None:
    """The time of REST's `resources.core.reset` (epoch seconds), `None` when `answer` is no
    such time or lies more than two hours after `read_at`."""
    if not (answer.isascii() and answer.isdigit()):
        return None
    try:
        reset = datetime.fromtimestamp(int(answer), UTC)
    except OverflowError, OSError, ValueError:
        return None
    return _within_the_window(reset, read_at)


def graphql_reset(answer: str, read_at: datetime) -> datetime | None:
    """The time of GraphQL's `rateLimit { resetAt }` (UTC, ISO 8601), `None` when `answer` is
    no such time or lies more than two hours after `read_at`."""
    try:
        reset = datetime.strptime(answer, _RESET_TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return _within_the_window(reset, read_at)


type ResetRead = Callable[[list[str]], str]
"""Runs the `gh` arguments it is given and answers the output; a failure is a `ForgeError`."""

# Each limit's reset comes from its own endpoint: REST's `rate_limit` is free, and GraphQL's
# own `rateLimit` query counts the limit the refused call hit. A secondary limit has none.
_RESET_READS: dict[RateLimit, tuple[list[str], Callable[[str, datetime], datetime | None]]] = {
    RateLimit.GRAPHQL: (
        ["api", "graphql", "-f", "query={rateLimit{resetAt}}", "--jq", ".data.rateLimit.resetAt"],
        graphql_reset,
    ),
    RateLimit.REST: (["api", "rate_limit", "--jq", ".resources.core.reset"], rest_reset),
}


def with_reset(limited: RateLimitedError, read: ResetRead) -> RateLimitedError:
    """`limited` with the reset its limit's owner states, read once through `read`; the reset
    stays unknown when the read fails or answers nothing plausible. `read` is never itself
    followed by a reset read."""
    reading = _RESET_READS.get(limited.limit)
    if reading is None:
        return RateLimitedError(limited.limit)
    arguments, parse = reading
    try:
        answer = read(list(arguments))
    except forge.ForgeError:
        return RateLimitedError(limited.limit)
    return RateLimitedError(limited.limit, parse(answer.strip(), datetime.now(UTC)))
