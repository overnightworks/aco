"""`aco land` where the default branch requires the merge queue: the landing message written
into the pull request, one enqueue pinned to the preflight head, the wait for the queue's
verdict and the re-run that picks it up again, against a fake forge that expresses the queue."""

from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from cli_fixtures import CliRun, run_cli
from github_fixtures import LandedWorld, landed_world, landing_readiness, serve_forge
from queue_forge import LANDS, QueueForge, QueueRead

from aco import cmd_land, cmd_land_queue, forge, github, protocol, store

NUMBER = 12
MINUTE = 60.0
FOREIGN_REPOSITORY = "fork/agent-providers"
CLASSIFIED = "Work-Item: #72\n\nCloses #72"
COMPOSED = "Closes #72\n\nWork-Item: #72\n"
TRAILERS = "Closes #72\n\nCo-Authored-By: A <a@x>\n\nWork-Item: #72"
TRAILERS_COMPOSED = "Closes #72\n\nCo-Authored-By: A <a@x>\nWork-Item: #72\n"
NOT_QUEUED = forge.UnqueuedPullRequest(None)
QUEUED = forge.QueuedPullRequest()
RELEASED = "RELEASED issue #72: landing\n"
CLEAN_CHECKOUT_REFUSAL = "ERROR: land must run from a clean checkout of the default branch 'main'\n"


def removed(reason: str) -> str:
    return (
        f"ERROR: pull request #{NUMBER} was removed from the merge queue ({reason}); "
        f"re-run aco land {NUMBER}\n"
    )


def removed_and_closed(reason: str) -> str:
    return f"ERROR: pull request #{NUMBER} was removed from the merge queue and closed ({reason})\n"


def not_queued(cause: str, failure: str) -> str:
    return (
        f"ERROR: pull request #{NUMBER} was not queued: {cause} failed ({failure}); "
        f"re-run aco land {NUMBER}\n"
    )


@dataclass(frozen=True)
class QueueCase:
    """What the forge says, in the order it says it, and what `land` makes of it. The
    defaults are a fresh landing: not queued, queued, merged."""

    reads: tuple[QueueRead, ...] = (NOT_QUEUED, QUEUED, LANDS)
    body: str = CLASSIFIED
    queue_rule: bool = True
    mergeable_state: str = "clean"
    untracked_file: bool = False
    head_repository: str | None = None
    head_moved: bool = False
    enqueue_error: forge.ForgeError | None = None
    rules_error: forge.ForgeError | None = None
    body_error: protocol.ClaimError | None = None
    status: int = 0
    stderr: str = ""
    written: tuple[str, ...] = (COMPOSED,)
    enqueues: int = 1
    pauses: int = 2
    direct_merges: int = 0


@dataclass
class QueueWorld:
    case: QueueCase
    landed: LandedWorld
    queue: QueueForge
    pauses: list[float]


@pytest.fixture
def world(
    request: pytest.FixtureRequest,
    github_clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> QueueWorld:
    case: QueueCase = request.param
    pauses: list[float] = []
    monkeypatch.setattr(cmd_land, "pause_between_reads", lambda _seconds: None)
    monkeypatch.setattr(cmd_land_queue, "pause_between_queue_reads", pauses.append)
    landed = landed_world(github_clone, bare_remote, monkeypatch, body=case.body)
    queue = QueueForge.over(landed.landing.forge)
    queue.closes_on_merge = True
    queue.queue_branches = {"main"} if case.queue_rule else set()
    queue.queue_reads = {NUMBER: list(case.reads)}
    queue.readiness_by_number[NUMBER] = landing_readiness(
        head_sha=landed.landing.head, mergeable_state=case.mergeable_state
    )
    queue.enqueue_error = case.enqueue_error
    queue.rules_error = case.rules_error
    queue.update_item_body_error = case.body_error
    if case.head_repository is not None:
        queue.landings[NUMBER] = replace(
            queue.landings[NUMBER], source_repository=github.repository_id(case.head_repository)
        )
    if case.head_moved:
        queue.heads[NUMBER] = "f" * 40
    if case.untracked_file:
        (github_clone / "untracked.txt").write_text("dirty\n")
    serve_forge(monkeypatch, queue)
    landed.landing.forge = queue
    return QueueWorld(case, landed, queue, pauses)


def observations(world: QueueWorld, result: CliRun) -> tuple[dict[str, object], dict[str, object]]:
    case, queue, landing = world.case, world.queue, world.landed.landing
    claims = store.peek_state(worktree=landing.clone, remote=str(landing.remote)).claims
    merged_line = f"merged: {queue.landings[NUMBER].merge_commit}\n"
    observed: dict[str, object] = {
        "exit": result.status,
        "stderr": result.stderr,
        "released": result.stdout.startswith(RELEASED),
        "merged line": merged_line in result.stdout,
        "claim kept": bool(claims),
        "branch deleted": bool(queue.deleted_branches),
        "written": tuple(body for _, body in queue.body_writes),
        "enqueued with": queue.enqueue_attempts,
        "direct merges": len(queue.merge_calls),
        "pauses": len(world.pauses),
        "pauses of a minute or more": min(world.pauses, default=MINUTE) >= MINUTE,
    }
    expected: dict[str, object] = {
        "exit": case.status,
        "stderr": case.stderr,
        "released": case.status == 0,
        "merged line": case.status == 0,
        "claim kept": case.status != 0,
        "branch deleted": case.status == 0,
        "written": case.written,
        "enqueued with": [(NUMBER, landing.head)] * case.enqueues,
        "direct merges": case.direct_merges,
        "pauses": case.pauses,
        "pauses of a minute or more": True,
    }
    return observed, expected


class TestLandThroughTheMergeQueue:
    @pytest.mark.parametrize(
        "world",
        [
            pytest.param(QueueCase(), id="enqueues-waits-and-releases"),
            pytest.param(
                QueueCase(body=TRAILERS, written=(TRAILERS_COMPOSED,)),
                id="a-body-ending-in-trailers-takes-the-classification-into-them",
            ),
            pytest.param(
                QueueCase(body=COMPOSED, written=()), id="a-composed-body-is-not-written-again"
            ),
            pytest.param(
                QueueCase(body=TRAILERS_COMPOSED, written=()),
                id="a-composed-body-with-trailers-is-not-written-again",
            ),
            pytest.param(
                QueueCase(reads=(NOT_QUEUED, NOT_QUEUED, QUEUED, NOT_QUEUED, LANDS), pauses=4),
                id="an-entry-missing-in-one-read-only-is-waited-out",
            ),
            pytest.param(
                QueueCase(
                    reads=(QUEUED, LANDS),
                    body=COMPOSED,
                    mergeable_state="dirty",
                    written=(),
                    enqueues=0,
                    pauses=1,
                ),
                id="a-re-run-finds-it-queued-and-waits-again",
            ),
            pytest.param(
                QueueCase(
                    reads=(forge.UnqueuedPullRequest("failed_checks"), QUEUED, LANDS),
                    body=COMPOSED,
                    written=(),
                ),
                id="a-re-run-finds-it-removed-and-queues-it-again",
            ),
            pytest.param(
                QueueCase(reads=(LANDS,), body=COMPOSED, written=(), enqueues=0, pauses=0),
                id="a-re-run-finds-it-merged-and-releases",
            ),
            pytest.param(
                QueueCase(
                    reads=(QUEUED, LANDS),
                    body=COMPOSED,
                    head_repository=FOREIGN_REPOSITORY,
                    status=2,
                    stderr=(
                        f"ERROR: pull request #{NUMBER} proposes a branch of "
                        f"{FOREIGN_REPOSITORY}; cross-repository pull requests are not classified\n"
                    ),
                    written=(),
                    enqueues=0,
                    pauses=0,
                ),
                id="a-queued-pull-request-of-another-repository-refuses-and-deletes-nothing",
            ),
            pytest.param(
                QueueCase(queue_rule=False, written=(), enqueues=0, pauses=0, direct_merges=1),
                id="without-a-queue-rule-the-merge-is-direct",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED, forge.UnqueuedPullRequest("failed_checks")),
                    status=2,
                    stderr=removed("failed_checks"),
                    pauses=1,
                ),
                id="removed-with-a-reason-refuses-naming-it",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED, QUEUED, NOT_QUEUED, NOT_QUEUED),
                    status=2,
                    stderr=removed("no reason recorded"),
                    pauses=3,
                ),
                id="missing-in-two-reads-in-a-row-is-removed-without-a-reason",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED, forge.ClosedPullRequest("failed_checks")),
                    status=2,
                    stderr=removed_and_closed("failed_checks"),
                    pauses=1,
                ),
                id="removed-and-closed-refuses-naming-the-reason",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED, forge.ClosedPullRequest(None)),
                    status=2,
                    stderr=removed_and_closed("no reason recorded"),
                    pauses=1,
                ),
                id="removed-and-closed-without-a-reason-says-so",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED, forge.ForgeTransientError("HTTP 502")),
                    status=2,
                    stderr=(
                        f"ERROR: reading the merge queue state of pull request #{NUMBER} failed "
                        f"(HTTP 502); re-run aco land {NUMBER}\n"
                    ),
                    pauses=1,
                ),
                id="a-failed-read-while-waiting-refuses-and-keeps-the-claim",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED,),
                    mergeable_state="dirty",
                    status=2,
                    stderr=f"ERROR: pull request #{NUMBER} is not mergeable (dirty)\n",
                    written=(),
                    enqueues=0,
                    pauses=0,
                ),
                id="a-failed-preflight-check-writes-and-queues-nothing",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED,),
                    untracked_file=True,
                    status=2,
                    stderr=CLEAN_CHECKOUT_REFUSAL,
                    written=(),
                    enqueues=0,
                    pauses=0,
                ),
                id="an-unclean-checkout-writes-and-queues-nothing",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED,),
                    body_error=protocol.ClaimError("update item body failed"),
                    status=2,
                    stderr=not_queued("writing its landing message", "update item body failed"),
                    written=(),
                    enqueues=0,
                    pauses=0,
                ),
                id="a-body-the-forge-refuses-is-no-enqueue",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED,),
                    head_moved=True,
                    status=2,
                    stderr=(
                        f"ERROR: pull request #{NUMBER} changed while it was checked; re-run land\n"
                    ),
                    pauses=0,
                ),
                id="a-head-that-moved-is-refused-after-one-enqueue",
            ),
            pytest.param(
                QueueCase(
                    reads=(NOT_QUEUED,),
                    enqueue_error=forge.ForgeTransientError("HTTP 502"),
                    status=2,
                    stderr=not_queued("enqueueing it", "HTTP 502"),
                    pauses=0,
                ),
                id="an-enqueue-that-fails-is-not-repeated",
            ),
            pytest.param(
                QueueCase(
                    rules_error=forge.ForgeTransientError("HTTP 502"),
                    status=2,
                    stderr=(
                        f"ERROR: pull request #{NUMBER} was not merged: reading its merge rules "
                        f"failed (HTTP 502); re-run aco land {NUMBER}\n"
                    ),
                    written=(),
                    enqueues=0,
                    pauses=0,
                ),
                id="rules-that-cannot-be-read-refuse-before-anything-is-written",
            ),
        ],
        indirect=True,
    )
    def test_land_queues_waits_and_releases_or_refuses(
        self, world: QueueWorld, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()
        result = run_cli(["land", str(NUMBER)], capsys)

        observed, expected = observations(world, result)

        assert observed == expected
