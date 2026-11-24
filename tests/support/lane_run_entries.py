"""Stored run entries of a lane, as `aco lane-record begin` and `add` leave them."""

import json
from collections.abc import Iterable
from pathlib import Path

from cli_fixtures import real_git
from lane_record_fixtures import four, lane_record_object, marked

from aco import lane_record, lane_runs, protocol, store
from aco.routing_line import RoutingStage

END_TIP = "b" * 40
START_TIP = "a" * 40


def begun(run: str, *, follows: bool = True, start_tip: str | None = None) -> lane_runs.RunEntry:
    """A run begun and not added."""
    return lane_runs.RunEntry(run, start_tip, follows)


def added(
    run: str,
    *ran: str,
    marker: str = "m",
    follows: bool = True,
    start_tip: str | None = None,
    **changes: object,
) -> lane_runs.RunEntry:
    """A run that ran `ran`, added with a record that states `changes` over a valid one whose
    stage choices carry `marker`; a change to `None` leaves the field out."""
    content = lane_record_object(
        **{"stages": marked(marker), "misses": four(0, 0, 0, 0), **changes}
    )
    stated = {name: value for name, value in content.items() if value is not None}
    record = lane_record.parse_record_file(json.dumps(stated).encode())
    stored = lane_runs.RunAdded(END_TIP, tuple(RoutingStage(stage) for stage in ran), record)
    return lane_runs.RunEntry(run, start_tip, follows, stored)


def not_following(run: str, *ran: str, marker: str = "m", **changes: object) -> lane_runs.RunEntry:
    """A run added that does not follow the run before it."""
    return added(run, *ran, marker=marker, follows=False, start_tip=START_TIP, **changes)


def commit_runs_file(
    directory: Path,
    remote: Path | str,
    claim_id: protocol.ClaimId,
    content: bytes,
    *,
    agent: str = "Ada",
) -> None:
    """The runs file of `claim_id` in `remote`'s state ref replaced by `content`, as `agent`
    holding the claim, over the file the state holds now."""
    observed = store.fetch_state(worktree=directory, remote=str(remote))
    store.commit_transition(
        observed=store.Observation(directory, str(remote), observed),
        subject=store.TransitionSubject("lane-record lane"),
        intent=protocol.RunsWriteIntent(
            claim_id=claim_id,
            agent=agent,
            expected=observed.runs.get(claim_id),
            new_oid=store.hash_blob(directory, content),
            operation_id=f"op-runs-{len(content)}",
            holder_refusal="{}".format,
            stale_refusal="never reached",
        ),
    )


def seed_approving_runs(
    landing_clone: Path, remote: Path, claims: Iterable[protocol.ActiveClaim], head: str
) -> protocol.ClaimState:
    """One stored run for each of `claims`, approving `head` with risk `normal`, published from
    a second clone so the landing clone stays unstamped; the state after them."""
    seed = landing_clone.parent / "runs-seed"
    real_git(landing_clone.parent, "clone", "-q", str(remote), str(seed))
    approval = {"stage": "review", "verdict": "approve", "sha": head}
    runs = lane_runs.RunsFile(
        (added("run-1", "build", "review", verdicts=[approval], risk="normal"),)
    )
    for claim in claims:
        content = lane_runs.serialize_runs(runs)
        commit_runs_file(seed, remote, claim.claim_id, content, agent=claim.agent)
    return store.peek_state(worktree=seed, remote=str(remote))
