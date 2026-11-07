"""The workflow runs GitHub Actions started by a push, read to tell them from manual ones."""

import json
from collections.abc import Callable, Iterable

from . import forge

PUSH_EVENT = "push"
WORKFLOW_RUNS_JQ = ".workflow_runs[] | {suite:.check_suite_id,event}"
Suites = frozenset[int] | None
MALFORMED_WORKFLOW_RUN = "GitHub returned a malformed workflow run"


def push_suites(
    run: Callable[[list[str]], str], repository: object, sha: str, *, push_only: bool
) -> Suites:
    """The check suites of the workflow runs at `sha` that a `push` started, or `None`
    when `push_only` is off and every check run counts."""
    if not push_only:
        return None
    raw = run(
        [
            "api",
            "--paginate",
            f"repos/{repository}/actions/runs?head_sha={sha}&per_page=100",
            "--jq",
            WORKFLOW_RUNS_JQ,
        ]
    )
    suites: set[int] = set()
    for line in raw.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise forge.ForgeMalformedResponseError(MALFORMED_WORKFLOW_RUN) from error
        suite = row.get("suite") if isinstance(row, dict) else None
        if isinstance(suite, bool) or not isinstance(suite, int):
            raise forge.ForgeMalformedResponseError(MALFORMED_WORKFLOW_RUN)
        if row.get("event") == PUSH_EVENT:
            suites.add(suite)
    return frozenset(suites)


def newest_per_name(
    rows: Iterable[tuple[int, forge.CheckRun, object]], suites: Suites
) -> tuple[forge.CheckRun, ...]:
    """Each check name's newest run (highest id); with `suites`, an Actions run (one with a
    check suite) counts only when its suite is among them, judged before the newest is chosen."""
    oldest_first = sorted(rows, key=lambda row: row[0])
    return tuple(
        {
            run.name: run
            for _, run, suite in oldest_first
            if suites is None or suite is None or suite in suites
        }.values()
    )
