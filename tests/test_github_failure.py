"""What a failed `gh` call means: a rate limit apart from a permission refusal, a missing
subject and a server failure, and the reset time GitHub names for a limit."""

from datetime import UTC, datetime, timedelta

import pytest
from rate_limit_fixtures import GRAPHQL_REFUSAL, REST_REFUSAL, SECONDARY_REFUSAL

from aco import forge, github_failure
from aco.github_failure import RateLimit

READ_AT = datetime(2026, 11, 19, 19, 46, tzinfo=UTC)
REST_429 = REST_REFUSAL.replace("(HTTP 403)", "(HTTP 429)")
SECONDARY_429 = SECONDARY_REFUSAL.replace("(HTTP 403)", "(HTTP 429)")
PHRASE_IN_BODY = '{"body":"gh: API rate limit already exceeded for user ID 1."}'
GRAPHQL_REACHED = "GitHub's GraphQL rate limit is reached; its reset time could not be read"
REST_REACHED = "GitHub's REST rate limit is reached; its reset time could not be read"
SECONDARY_REACHED = "GitHub's secondary rate limit is reached; try again in a minute"


def classified(text: str, limit: RateLimit = RateLimit.REST) -> forge.ForgeError:
    return github_failure.nonzero_exit_failure(text, 1, "a test call", request_limit=limit)


@pytest.mark.parametrize(
    ("text", "requested", "sentence"),
    [
        pytest.param(GRAPHQL_REFUSAL, RateLimit.GRAPHQL, GRAPHQL_REACHED, id="recorded-graphql"),
        pytest.param(GRAPHQL_REFUSAL, RateLimit.REST, REST_REACHED, id="the-requests-own-limit"),
        pytest.param(REST_REFUSAL, RateLimit.REST, REST_REACHED, id="rest-403"),
        pytest.param(REST_429, RateLimit.REST, REST_REACHED, id="rest-429"),
        pytest.param(REST_429, RateLimit.GRAPHQL, GRAPHQL_REACHED, id="rest-429-graphql"),
        pytest.param(SECONDARY_REFUSAL, RateLimit.GRAPHQL, SECONDARY_REACHED, id="secondary-403"),
        pytest.param(SECONDARY_429, RateLimit.REST, SECONDARY_REACHED, id="secondary-429"),
        pytest.param(
            "gh: Too Many Requests (HTTP 429)", RateLimit.REST, SECONDARY_REACHED, id="bare-429"
        ),
        pytest.param(
            "gh: Too Many Requests (HTTP 429)",
            RateLimit.GRAPHQL,
            SECONDARY_REACHED,
            id="bare-429-graphql",
        ),
    ],
)
def test_a_rate_limit_is_a_transient_error_naming_the_limit_and_no_reset(
    text: str, requested: RateLimit, sentence: str
) -> None:
    """Spec: OUT-13, OUT-12 -- gh's closing message or an HTTP 429 marks a rate limit; it is
    secondary when gh says so or when only a 429 is known, else the request's own limit."""
    error = classified(text, requested)

    assert isinstance(error, forge.ForgeRateLimitedError)
    assert (str(error), error.resets_at) == (sentence, None)
    assert isinstance(error, forge.ForgeTransientError)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "gh: Resource not accessible by integration (HTTP 403)",
            forge.ForgePermissionDeniedError,
            id="permission-integration",
        ),
        pytest.param(
            "gh: Upgrade to GitHub Pro or make this repository public (HTTP 403)",
            forge.ForgePermissionDeniedError,
            id="permission-plan",
        ),
        pytest.param(
            f"{PHRASE_IN_BODY}gh: Not Found (HTTP 404)",
            forge.ForgeNotFoundError,
            id="phrase-in-json-then-404",
        ),
        pytest.param(
            f"{PHRASE_IN_BODY}gh: Bad Gateway (HTTP 502)",
            forge.ForgeTransientError,
            id="phrase-in-json-then-502",
        ),
        pytest.param(
            '{"message":"gh: API rate limit exceeded for user ID 1."}\n'
            "gh: Resource not accessible by integration (HTTP 403)",
            forge.ForgePermissionDeniedError,
            id="phrase-in-json-then-403",
        ),
        pytest.param(PHRASE_IN_BODY, forge.ForgeError, id="phrase-in-json"),
        pytest.param(
            '{"errors":[{"message":"gh: You have exceeded a secondary rate limit"}]}',
            forge.ForgeError,
            id="whole-gh-message-quoted-in-json",
        ),
        pytest.param(
            "gh: API rate limit exceeded for user ID 1.\ndiff --git a/f b/f",
            forge.ForgeError,
            id="phrase-then-a-line-break",
        ),
        pytest.param("gh: the secondary rate limit", forge.ForgeError, id="other-words"),
        pytest.param("", forge.ForgeError, id="no-output"),
    ],
)
def test_text_that_is_not_gh_closing_a_rate_limit_keeps_its_type(
    text: str, expected: type[forge.ForgeError]
) -> None:
    """Spec: OUT-13 -- a body, a diff, a JSON answer or a 403 that names no rate limit is
    never read as one."""
    error = classified(text)

    assert type(error) is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param("1795118883", datetime(2026, 11, 19, 20, 8, 3, tzinfo=UTC), id="epoch"),
        pytest.param("1795117000", datetime(2026, 11, 19, 19, 36, 40, tzinfo=UTC), id="past"),
        pytest.param("soon", None, id="malformed"),
        pytest.param("", None, id="empty"),
        pytest.param("-5", None, id="negative"),
        pytest.param("1795118883.5", None, id="fractional"),
        pytest.param("99999999999999999999", None, id="out-of-range"),
        pytest.param("1795124761", None, id="more-than-two-hours-ahead"),
        pytest.param("1795124760", datetime(2026, 11, 19, 21, 46, tzinfo=UTC), id="two-hours"),
    ],
)
def test_the_rest_reset_is_an_epoch_time_within_two_hours_of_the_read(
    answer: str, expected: datetime | None
) -> None:
    """Spec: OUT-13 -- a malformed or implausible reset leaves the reset unknown; one
    already past is kept."""
    assert github_failure.rest_reset(answer, READ_AT) == expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param("2026-11-19T20:15:27Z", datetime(2026, 11, 19, 20, 15, 27, tzinfo=UTC)),
        pytest.param("2026-11-19T19:00:00Z", datetime(2026, 11, 19, 19, 0, tzinfo=UTC), id="past"),
        pytest.param("2026-11-19T20:15:27+01:00", None, id="offset"),
        pytest.param("20:15:27", None, id="time-only"),
        pytest.param("null", None, id="null"),
        pytest.param("", None, id="empty"),
        pytest.param("2026-11-19T21:46:01Z", None, id="more-than-two-hours-ahead"),
        pytest.param("2026-11-19T21:46:00Z", datetime(2026, 11, 19, 21, 46, tzinfo=UTC), id="edge"),
    ],
)
def test_the_graphql_reset_is_an_utc_time_within_two_hours_of_the_read(
    answer: str, expected: datetime | None
) -> None:
    """Spec: OUT-13 -- the same bound as REST's reset."""
    assert github_failure.graphql_reset(answer, READ_AT) == expected


def test_the_two_hour_bound_counts_from_the_read() -> None:
    reset = READ_AT + timedelta(hours=3)
    answer = reset.strftime("%Y-%m-%dT%H:%M:%SZ")

    after_an_hour = github_failure.graphql_reset(answer, READ_AT + timedelta(hours=1))

    assert (github_failure.graphql_reset(answer, READ_AT), after_an_hour) == (None, reset)
