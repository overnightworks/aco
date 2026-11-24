"""`aco land` of a lane whose claim holds stored runs: it judges their verdicts and refuses
`--record FILE` beside them before any merge, on every path of the command, then writes the
trailers from the runs, and refuses when the runs changed after it read them
(`specs/lane-record.spec.md`, "Stored runs")."""

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

import pytest
from cli_fixtures import CliRun, real_git, run_cli
from github_fixtures import (
    LaneLandingWorld,
    arrange_follow_up_failures,
    landed_world,
    landing_effects,
    serve_forge,
)
from landing_refusals import refusal_observations
from lane_record_fixtures import lane_record_object, write_lane_record_file
from lane_record_runs_world import (
    LANDING_CLAIM_ID,
    SINGLE_RUN_TRAILERS,
    SUMMED_TRAILERS,
    THIRD_RUN,
    a_run_stored_late,
    chained_runs,
    commit_runs_file,
    race_before_the_push,
    record_stating,
    routing_trailers_of,
    stale_runs_sentence,
    two_chained_runs,
)
from queue_forge import LANDS, QueueForge, QueueRead
from store_fixtures import claim_intent

from aco import cmd_land_queue, forge, lane_runs, protocol, store

BRANCH = "codex/issue-72-claims"
RELEASE_AGAIN = ["release", "72", "--merged", "12", "--branch", BRANCH]
WAITING = "waiting for pull request #12 in the merge queue\n"
QUEUED = forge.QueuedPullRequest()
NOT_QUEUED = forge.UnqueuedPullRequest(None)
SENTENCE_OF_BOTH = "#72 has stored runs, so aco computes its record from them; drop --record"
# The body the landing message already holds once the pull request was queued.
COMPOSED_BODY = "Closes #72\n\nWork-Item: #72\n"
NO_VERDICT = "the lane record states no review or gate verdict, so it judged no head to land"
QueueStanding = tuple[list[tuple[int, str]], dict[int, forge.MergeQueueState]]


class LandPath(StrEnum):
    DIRECT = "direct merge"
    ENQUEUE = "enqueue"
    ALREADY_QUEUED = "already queued"
    RERUN_AFTER_MERGE = "rerun after the merge"
    RERUN_AFTER_QUEUE_DROP = "rerun after a queue drop"


QUEUE_READS: dict[LandPath, list[QueueRead]] = {
    LandPath.ENQUEUE: [NOT_QUEUED, QUEUED, LANDS],
    LandPath.ALREADY_QUEUED: [QUEUED, LANDS],
    LandPath.RERUN_AFTER_QUEUE_DROP: [forge.UnqueuedPullRequest("failed_checks"), QUEUED, LANDS],
}
ALL_PATHS = [pytest.param(path, id=path.name.lower().replace("_", "-")) for path in LandPath]


@dataclass(frozen=True)
class Arranged:
    """A lane on one path of `aco land`, with the merge queue where the path goes through it."""

    lane: LaneLandingWorld
    queue: QueueForge | None

    def stderr_of_a_landing(self) -> str:
        return "" if self.queue is None else WAITING

    def queue_standing(self) -> QueueStanding:
        if self.queue is None:
            return [], {}
        return list(self.queue.enqueue_attempts), dict(self.queue.queue_states)


@pytest.fixture
def landing(
    github_clone: Path, bare_remote: Path, monkeypatch: pytest.MonkeyPatch
) -> LaneLandingWorld:
    return landed_world(github_clone, bare_remote, monkeypatch).landing


@pytest.fixture
def lane(landing: LaneLandingWorld) -> LaneLandingWorld:
    store_runs(landing, two_chained_runs([verdict("approve", landing.head)]))
    return landing


def verdict(kind: str, sha: str, stage: str = "review") -> dict[str, str]:
    return {"stage": stage, "verdict": kind, "sha": sha}


def store_runs(lane: LaneLandingWorld, runs: lane_runs.RunsFile | bytes) -> None:
    """The runs of the lane's claim, whatever bytes they are; the lane's unchanged effects are
    taken again, since storing them reads and stamps the clone's state."""
    content = runs if isinstance(runs, bytes) else lane_runs.serialize_runs(runs)
    commit_runs_file(lane.clone, lane.remote, LANDING_CLAIM_ID, content)
    lane.unchanged = landing_effects(lane)


def arranged(
    lane: LaneLandingWorld,
    path: LandPath,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> Arranged:
    """`lane` set up so that `aco land` takes `path`; the lane's runs are stored after."""
    if path is LandPath.RERUN_AFTER_MERGE:
        arrange_follow_up_failures(lane.forge, None, "branch deletion failed")
        merged = run_cli(["land", "12", "--head", lane.head], capsys)
        assert merged.status == 2
        lane.forge.delete_error = None
        lane.unchanged = landing_effects(lane)
    if path not in QUEUE_READS:
        return Arranged(lane, None)
    monkeypatch.setattr(cmd_land_queue, "pause_between_queue_reads", [].append)
    queue = QueueForge.over(lane.forge)
    queue.closes_on_merge = True
    queue.queue_branches = {"main"}
    queue.queue_reads = {12: list(QUEUE_READS[path])}
    if path is LandPath.ALREADY_QUEUED:
        queue.queue_states[12] = QUEUED
        queue.landings[12] = replace(queue.landings[12], body=COMPOSED_BODY)
    serve_forge(monkeypatch, queue)
    lane.forge = queue
    return Arranged(lane, queue)


def runs_files_in_state(lane: LaneLandingWorld) -> int:
    return real_git(lane.remote, "ls-tree", "-r", store.STATE_REF).stdout.count("runs/")


def follow_up_incomplete(release_refusal: str) -> str:
    """What `aco land` prints when the merge landed and its release refused with
    `release_refusal`."""
    return (
        "ERROR: MERGED pull request #12 as <sha>; follow-up incomplete: "
        f"release ({release_refusal}); re-run aco land 12 --head <sha>\n"
    )


def printed_without_the_merge_sha(stderr: str) -> str:
    return re.sub(r"as [0-9a-f]{40};", "as <sha>;", stderr)


def refused_observations(
    standing: Arranged, result: CliRun, sentence: str, queue_before: QueueStanding
) -> tuple[dict[str, object], dict[str, object]]:
    """What a refused land changed: nothing the landing world observes, nothing enqueued and
    no entry of the queue removed or added."""
    observed, expected = refusal_observations(standing.lane, result, sentence)
    observed["queue"] = standing.queue_standing()
    expected["queue"] = ([], queue_before[1])
    return observed, expected


def landed_observations(
    standing: Arranged, result: CliRun
) -> tuple[dict[str, object], dict[str, object]]:
    lane = standing.lane
    observed: dict[str, object] = {
        "exit": result.status,
        "stderr": result.stderr,
        "merged": lane.forge.landings[12].merged,
        "runs files": runs_files_in_state(lane),
        "claims": store.peek_state(worktree=lane.clone, remote=str(lane.remote)).claims,
    }
    expected: dict[str, object] = {
        "exit": 0,
        "stderr": standing.stderr_of_a_landing(),
        "merged": True,
        "runs files": 0,
        "claims": {},
    }
    return observed, expected


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(
    ("chained", "trailers"),
    [(1, SINGLE_RUN_TRAILERS), (2, SUMMED_TRAILERS)],
    ids=["one-run", "two-chained-runs"],
)
def test_a_landing_whose_last_stored_verdict_approves_the_head_writes_the_trailers_of_the_runs(
    landing: LaneLandingWorld,
    path: LandPath,
    chained: int,
    trailers: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-97, LANREC-98, LANREC-90 -- on every path the runs of the claim are the
    record, the merge pins `--head` and the release drops the runs."""
    standing = arranged(landing, path, monkeypatch, capsys)
    record = record_stating(verdicts=[verdict("approve", landing.head)])
    store_runs(landing, chained_runs(*[record] * chained))

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    observed, expected = landed_observations(standing, result)
    assert observed == expected
    assert routing_trailers_of(landing.remote) == trailers


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(
    ("verdicts", "sentence"),
    [
        pytest.param(
            [verdict("approve", "{head}"), verdict("revise", "{head}", "gate")],
            "the lane record's last verdict is revise at gate, not approve",
            id="a-last-verdict-that-is-no-approval",
        ),
        pytest.param(
            [verdict("approve", "d" * 40)],
            "the lane record's last verdict judged " + "d" * 40 + ", not the reviewed {head}",
            id="a-last-verdict-on-another-commit",
        ),
    ],
)
def test_a_landing_whose_last_stored_verdict_is_no_approval_of_the_head_refuses_before_any_merge(
    landing: LaneLandingWorld,
    path: LandPath,
    verdicts: list[dict[str, str]],
    sentence: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-97, LANREC-98, LANREC-38, LANREC-44 -- nothing is merged, enqueued, deleted
    or written, and a pull request already queued stays queued."""
    standing = arranged(landing, path, monkeypatch, capsys)
    stated = [{**item, "sha": item["sha"].format(head=landing.head)} for item in verdicts]
    store_runs(landing, chained_runs(record_stating(verdicts=stated)))
    queue_before = standing.queue_standing()

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    observed, expected = refused_observations(
        standing, result, sentence.format(head=landing.head), queue_before
    )
    assert observed == expected


@pytest.mark.parametrize(
    "runs",
    [chained_runs(record_stating(verdicts=[])), chained_runs(None)],
    ids=["a-record-without-a-verdict", "a-run-begun-and-never-added"],
)
def test_a_landing_whose_stored_runs_hold_no_verdict_refuses_before_any_merge(
    landing: LaneLandingWorld, runs: lane_runs.RunsFile, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-97, LANREC-39."""
    store_runs(landing, runs)

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    observed, expected = refusal_observations(landing, result, NO_VERDICT)
    assert observed == expected


def test_a_landing_whose_newest_run_has_no_record_lands_on_the_last_stored_approval(
    landing: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-97 -- the verdicts are those of the runs that have a record."""
    store_runs(
        landing, chained_runs(record_stating(verdicts=[verdict("approve", landing.head)]), None)
    )

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    assert (result.status, result.stderr, landing.forge.landings[12].merged) == (0, "", True)


def test_a_landing_whose_newest_run_has_no_record_refuses_on_the_last_stored_revision(
    landing: LaneLandingWorld, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-97, LANREC-44."""
    store_runs(
        landing, chained_runs(record_stating(verdicts=[verdict("revise", landing.head)]), None)
    )

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    sentence = "the lane record's last verdict is revise at review, not approve"
    observed, expected = refusal_observations(landing, result, sentence)
    assert observed == expected


@pytest.mark.parametrize("path", ALL_PATHS)
def test_a_landing_with_stored_runs_and_a_record_file_refuses_before_any_merge(
    landing: LaneLandingWorld,
    path: LandPath,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: LANREC-98, LANREC-91 -- the runs file stays, the claim is kept and the
    branch is not deleted. Example: E-LANREC-20."""
    standing = arranged(landing, path, monkeypatch, capsys)
    store_runs(landing, two_chained_runs([verdict("approve", landing.head)]))
    record = write_lane_record_file(
        tmp_path, lane_record_object(verdicts=[verdict("approve", landing.head, "gate")])
    )
    queue_before = standing.queue_standing()

    result = run_cli(["land", "12", "--head", landing.head, "--record", str(record)], capsys)

    observed, expected = refused_observations(standing, result, SENTENCE_OF_BOTH, queue_before)
    assert observed == expected
    assert runs_files_in_state(landing) == 1


def test_a_landing_whose_stored_runs_file_holds_no_run_takes_the_record_file_as_today(
    landing: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-98 -- a claim whose runs file holds no run stores no runs, so it is judged
    by the record file."""
    store_runs(landing, b'{"version": 1, "runs": []}')
    record = write_lane_record_file(
        tmp_path, lane_record_object(verdicts=[verdict("approve", landing.head, "gate")])
    )

    result = run_cli(["land", "12", "--head", landing.head, "--record", str(record)], capsys)

    assert (result.status, result.stderr) == (0, "")
    assert "lane_test: sonnet-5.5/medium" in routing_trailers_of(landing.remote)


@pytest.mark.parametrize(
    ("content", "defect"),
    [
        pytest.param(b"not json", "not valid JSON", id="not-json"),
        pytest.param(b'{"version": 2, "runs": []}', "version must be the whole number 1", id="v2"),
    ],
)
def test_a_landing_whose_stored_runs_cannot_be_read_refuses_before_any_merge(
    landing: LaneLandingWorld, content: bytes, defect: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-97, LANREC-62 -- the evidence of the review cannot be judged."""
    store_runs(landing, content)

    result = run_cli(["land", "12", "--head", landing.head], capsys)

    observed, expected = refusal_observations(
        landing, result, f"the stored runs of #72 cannot be used: {defect}"
    )
    assert observed == expected
    assert runs_files_in_state(landing) == 1


def test_a_refused_rerun_after_a_merge_is_released_by_hand_and_the_land_again_deletes_the_branch(
    landing: LaneLandingWorld, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-98 -- with no live claim left the guard judges nothing."""
    arranged(landing, LandPath.RERUN_AFTER_MERGE, monkeypatch, capsys)
    store_runs(landing, chained_runs(record_stating(verdicts=[verdict("revise", landing.head)])))
    refused = run_cli(["land", "12", "--head", landing.head], capsys)
    assert (refused.status, landing.forge.deleted_branches) == (2, [])

    released = run_cli(RELEASE_AGAIN, capsys)
    landed = run_cli(["land", "12", "--head", landing.head], capsys)

    assert (released.status, released.stderr) == (0, "")
    assert (landed.status, landed.stderr, landing.forge.deleted_branches) == (0, "", [BRANCH])


def test_a_landing_whose_stored_runs_stand_on_another_branch_takes_the_record_file_as_today(
    landing: LaneLandingWorld, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: LANREC-98 -- only the runs of the claims on the pull request's head branch count."""
    base = protocol.ObjectId(real_git(landing.clone, "rev-parse", "main").stdout.strip())
    observed = store.fetch_state(worktree=landing.clone, remote=str(landing.remote))
    store.commit_transition(
        observed=store.Observation(landing.clone, str(landing.remote), observed),
        subject=store.TransitionSubject("claim"),
        intent=claim_intent(
            identity=protocol.IssueIdentity(73),
            branch="codex/issue-73-other",
            claim_id="other",
            scope=("src/other.py",),
            operation_id="op-other",
            base=base,
        ),
    )
    commit_runs_file(
        landing.clone,
        landing.remote,
        protocol.ClaimId("other"),
        lane_runs.serialize_runs(two_chained_runs()),
    )
    record = write_lane_record_file(
        tmp_path, lane_record_object(verdicts=[verdict("approve", landing.head, "gate")])
    )

    result = run_cli(["land", "12", "--head", landing.head, "--record", str(record)], capsys)

    assert (result.status, result.stderr) == (0, "")
    assert "lane_test: sonnet-5.5/medium" in routing_trailers_of(landing.remote)


def test_a_run_added_between_the_releases_read_and_its_push_ends_the_landing_and_the_rerun_sums_it(
    lane: LaneLandingWorld, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec: LANREC-92 -- the merge stands; the claim and its runs stay until the rerun."""
    race_before_the_push(
        monkeypatch, a_run_stored_late(lane.clone, lane.remote, LANDING_CLAIM_ID, THIRD_RUN)
    )

    refused = run_cli(["land", "12", "--head", lane.head], capsys)

    assert (refused.status, printed_without_the_merge_sha(refused.stderr)) == (
        2,
        follow_up_incomplete(stale_runs_sentence("#72")),
    )
    assert runs_files_in_state(lane) == 1

    rerun = run_cli(["land", "12", "--head", lane.head], capsys)

    assert (rerun.status, rerun.stderr) == (0, "")
    assert {"lane_fix_rounds: 9", "lane_blocking: 12"} <= set(routing_trailers_of(lane.remote))
    assert runs_files_in_state(lane) == 0
