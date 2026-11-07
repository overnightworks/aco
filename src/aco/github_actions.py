"""The workflow runs GitHub Actions started by a push, read to tell them from manual ones."""

from collections.abc import Callable, Iterable

from . import forge

PUSH_EVENT = "push"
WORKFLOW_RUNS_JQ = ".workflow_runs[] | {suite:.check_suite_id,event}"
Suites = frozenset[int] | None
MALFORMED_WORKFLOW_RUN = "GitHub returned a malformed workflow run"
MALFORMED_CHECK_RUN = "GitHub returned a malformed check run"


def push_suites(
    read: Callable[[list[str]], tuple[object, ...]],
    repository: forge.RepositoryId,
    sha: str,
    *,
    push_only: bool,
) -> Suites:
    """The check suites of the workflow runs at `sha` that a `push` started, or `None`
    when `push_only` is off and every check run counts."""
    if not push_only:
        return None
    rows = read(
        [
            "api",
            "--paginate",
            f"repos/{repository}/actions/runs?head_sha={sha}&per_page=100",
            "--jq",
            WORKFLOW_RUNS_JQ,
        ]
    )
    suites: set[int] = set()
    for row in rows:
        fields = row if isinstance(row, dict) else {}
        suite = fields.get("suite")
        if isinstance(suite, bool) or not isinstance(suite, int):
            raise forge.ForgeMalformedResponseError(MALFORMED_WORKFLOW_RUN)
        event = fields.get("event")
        if not isinstance(event, str) or not event:
            raise forge.ForgeMalformedResponseError(MALFORMED_WORKFLOW_RUN)
        if event == PUSH_EVENT:
            suites.add(suite)
    return frozenset(suites)


def newest_per_name(
    rows: Iterable[tuple[int, forge.CheckRun, object]], suites: Suites
) -> tuple[forge.CheckRun, ...]:
    """Each check name's newest run (highest id); with `suites`, an Actions run (one with a
    check suite) counts only when its suite is among them, judged before the newest is chosen."""
    oldest_first = sorted(rows, key=lambda row: row[0])
    for _, _, suite in oldest_first:
        if suite is not None and (isinstance(suite, bool) or not isinstance(suite, int)):
            raise forge.ForgeMalformedResponseError(MALFORMED_CHECK_RUN)
    return tuple(
        {
            run.name: run
            for _, run, suite in oldest_first
            if suites is None or suite is None or suite in suites
        }.values()
    )
