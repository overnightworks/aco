"""After a rate limit the GitHub adapter reads the reset time once from the endpoint that owns
that limit. The GitHub CLI is the only fake: a `gh` on `PATH` that refuses every call and
answers the reset reads as the test chose."""

import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from rate_limit_fixtures import GRAPHQL_REFUSAL, REST_REFUSAL, SECONDARY_REFUSAL

from aco import forge, github, github_probe

# Logs each call's arguments in `FAKE_GH_LOG`; answers a reset read (REST's `rate_limit` or
# GraphQL's `rateLimit` query) with `FAKE_GH_RESET` when set; refuses every other call and a
# reset read without an answer with `FAKE_GH_REFUSAL`.
FAKE_GH = """#!{python}
import json, os, sys

arguments = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(arguments) + "\\n")
reads_a_reset = "rate_limit" in arguments or any("rateLimit" in argument for argument in arguments)
if reads_a_reset and "FAKE_GH_RESET" in os.environ:
    print(os.environ["FAKE_GH_RESET"])
    sys.exit(0)
print(os.environ["FAKE_GH_REFUSAL"], file=sys.stderr)
sys.exit(1)
"""
REPOSITORY = github.repository_id("example/agent-coordination")
RestCall = Callable[[github.GitHubForge], object]


def refusing_gh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refusal: str, reset: str | None = None
) -> Path:
    """A `gh` on `PATH` as described above; returns the file listing its calls."""
    shims = tmp_path / "gh-bin"
    shims.mkdir()
    log = tmp_path / "gh-calls.log"
    fake_gh = shims / "gh"
    fake_gh.write_text(FAKE_GH.format(python=sys.executable))
    fake_gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shims}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_LOG", str(log))
    monkeypatch.setenv("FAKE_GH_REFUSAL", refusal)
    if reset is not None:
        monkeypatch.setenv("FAKE_GH_RESET", reset)
    return log


def calls_of(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def reset_in(delta: timedelta) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) + delta


def epoch(moment: datetime) -> str:
    return str(int(moment.timestamp()))


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.parametrize(
    ("limit", "refusal", "reset_answer", "reset_read"),
    [
        pytest.param("REST", REST_REFUSAL, epoch, "rate_limit", id="rest"),
        pytest.param("GraphQL", GRAPHQL_REFUSAL, iso, "query={rateLimit{resetAt}}", id="graphql"),
    ],
)
def test_a_refused_call_reads_the_reset_from_the_limits_own_endpoint_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    limit: str,
    refusal: str,
    reset_answer: Callable[[datetime], str],
    reset_read: str,
) -> None:
    """Spec: OUT-13 -- the reset is the one the limit's owner states; the read counts as a
    request and is not followed by another."""
    reset = reset_in(timedelta(minutes=30))
    log = refusing_gh(monkeypatch, tmp_path, refusal, reset_answer(reset))
    client = github.GitHubForge(REPOSITORY)
    refused_call = client.default_branch if limit == "REST" else lambda: client.merge_queue_state(7)

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        refused_call()

    sentence = f"GitHub's {limit} rate limit is reached; it resets at {iso(reset)}"
    calls = calls_of(log)
    assert (str(caught.value), caught.value.resets_at, client.requests, len(calls)) == (
        sentence,
        reset,
        2,
        2,
    )
    assert reset_read in calls[1]


@pytest.mark.parametrize(
    "reset_answer",
    [
        pytest.param(None, id="refused"),
        pytest.param("soon", id="malformed"),
        pytest.param(epoch(reset_in(timedelta(hours=3))), id="more-than-two-hours-ahead"),
    ],
)
def test_a_reset_that_could_not_be_read_stays_unknown_and_is_not_read_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reset_answer: str | None
) -> None:
    """Spec: OUT-13 -- a refused, malformed or implausible reset read changes nothing else:
    the error is the rate limit, its reset unknown."""
    log = refusing_gh(monkeypatch, tmp_path, REST_REFUSAL, reset_answer)
    client = github.GitHubForge(REPOSITORY)

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        client.default_branch()

    sentence = "GitHub's REST rate limit is reached; its reset time could not be read"
    assert (str(caught.value), caught.value.resets_at, client.requests, len(calls_of(log))) == (
        sentence,
        None,
        2,
        2,
    )


def test_a_secondary_limit_reads_no_reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Spec: OUT-13 -- a secondary limit names no reset to read."""
    log = refusing_gh(monkeypatch, tmp_path, SECONDARY_REFUSAL, epoch(reset_in(timedelta(hours=1))))
    client = github.GitHubForge(REPOSITORY)

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        client.default_branch()

    sentence = "GitHub's secondary rate limit is reached; try again in a minute"
    assert (str(caught.value), client.requests, len(calls_of(log))) == (sentence, 1, 1)


def test_a_call_outside_the_forge_reads_no_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: OUT-13 -- the ruling search's runner is not the forge's: it gets the sentence
    without a reset read."""
    log = refusing_gh(monkeypatch, tmp_path, REST_REFUSAL, epoch(reset_in(timedelta(hours=1))))

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        github.bounded_command(["gh", "api", "search/issues"], purpose="the ruling search")

    assert (caught.value.resets_at, len(calls_of(log))) == (None, 1)


def test_a_refused_search_names_the_search_rate_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: OUT-13 -- a search call spends the search quota, so its refusal names that limit."""
    refusing_gh(monkeypatch, tmp_path, REST_REFUSAL)

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        github.bounded_command(["gh", "api", "search/issues"], purpose="the ruling search")

    assert (
        str(caught.value)
        == "GitHub's search rate limit is reached; its reset time could not be read"
    )


def test_the_conditional_probe_reads_the_reset_through_its_own_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: WAIT-22 -- the probe is a call of its own, and its rate limit carries the reset."""
    reset = reset_in(timedelta(minutes=30))
    log = refusing_gh(monkeypatch, tmp_path, REST_REFUSAL, epoch(reset))
    probe = github_probe.GitHubBoardProbe(github.response_command)
    target = forge.ProbeTarget(str(REPOSITORY))

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        probe.changed_since(target, None)

    calls = calls_of(log)
    assert (caught.value.resets_at, len(calls)) == (reset, 2)
    assert (calls[0][:2], calls[1][:2]) == (["api", "-i"], ["api", "rate_limit"])


def test_a_probe_whose_reset_read_is_refused_leaves_the_reset_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Spec: WAIT-22 -- the probe's own reset read is never followed by another."""
    log = refusing_gh(monkeypatch, tmp_path, REST_REFUSAL)
    probe = github_probe.GitHubBoardProbe(github.response_command)
    target = forge.ProbeTarget(str(REPOSITORY))

    with pytest.raises(forge.ForgeRateLimitedError) as caught:
        probe.changed_since(target, None)

    assert (caught.value.resets_at, len(calls_of(log))) == (None, 2)
