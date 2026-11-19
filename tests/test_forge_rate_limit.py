"""The rate-limit error the forge port carries and the sentence the GitHub adapter gives it."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from aco import github_failure
from aco.github_failure import RateLimit

RESET = datetime(2026, 11, 19, 20, 15, 27, tzinfo=UTC)
BODY_WRITE_CAUSE_LIMIT = 80


@pytest.mark.parametrize(
    ("limit", "resets_at", "sentence"),
    [
        pytest.param(
            RateLimit.GRAPHQL,
            RESET,
            "GitHub's GraphQL rate limit is reached; it resets at 2026-11-19T20:15:27Z",
            id="graphql",
        ),
        pytest.param(
            RateLimit.REST,
            RESET,
            "GitHub's REST rate limit is reached; it resets at 2026-11-19T20:15:27Z",
            id="rest",
        ),
        pytest.param(
            RateLimit.REST,
            RESET - timedelta(days=1),
            "GitHub's REST rate limit is reached; it resets at 2026-11-18T20:15:27Z",
            id="a-reset-already-past",
        ),
        pytest.param(
            RateLimit.REST,
            RESET.astimezone(timezone(timedelta(hours=2))),
            "GitHub's REST rate limit is reached; it resets at 2026-11-19T20:15:27Z",
            id="stated-in-utc",
        ),
        pytest.param(
            RateLimit.GRAPHQL,
            None,
            "GitHub's GraphQL rate limit is reached; its reset time could not be read",
            id="graphql-without-a-reset",
        ),
        pytest.param(
            RateLimit.REST,
            None,
            "GitHub's REST rate limit is reached; its reset time could not be read",
            id="rest-without-a-reset",
        ),
        pytest.param(
            RateLimit.SECONDARY,
            None,
            "GitHub's secondary rate limit is reached; try again in a minute",
            id="secondary",
        ),
    ],
)
def test_the_sentence_names_the_limit_and_its_reset_within_what_a_body_write_shows(
    limit: RateLimit, resets_at: datetime | None, sentence: str
) -> None:
    """Spec: OUT-13 -- the three sentences; each fits the 80 characters a body write shows of
    its cause and names no permission, body or repository."""
    error = github_failure.RateLimitedError(limit, resets_at)

    assert str(error) == sentence
    assert len(sentence) <= BODY_WRITE_CAUSE_LIMIT
