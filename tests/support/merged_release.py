"""A merged pull request arranged in the order the forge does: a real merge or squash
commit on the bare remote, then the claim on the real state ref (none when `identity` is
None: the state a rerun finds after a completed release)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from cli_fixtures import landed_from_another_clone, push_lane_branch, real_git
from github_fixtures import (
    LANDING_BRANCH,
    FakeForge,
    landing_pull_request,
    merge_on_the_forge,
    serve_forge,
)
from store_fixtures import claim_intent, publish_claims_from_a_second_clone

from aco import protocol, store
from aco.workboard import MergeMethod

PULL_REQUEST = 12
LANDING_TITLE = "feat: land the lane (#12)"


@dataclass(frozen=True)
class MergedPullRequest:
    forge: FakeForge
    merge_commit: str
    claim_base: str


def arrange_merged_pull_request(
    monkeypatch: pytest.MonkeyPatch,
    clone: Path,
    remote: Path,
    *,
    identity: protocol.ClaimIdentity | None,
    trailers: tuple[str, ...],
    pull_request_body: str,
    branch: str = LANDING_BRANCH,
    claim_branch: str | None = None,
    method: MergeMethod = MergeMethod.MERGE,
    forge_base: str = "main",
    forge_reports_merged: bool = True,
    forge_merge_commit: str | None = None,
    claim_after_the_merge: tuple[str, ...] | None = None,
) -> MergedPullRequest:
    """`trailers` end the merge commit's message, the authority a release reads;
    `pull_request_body` is the forge's mutable text. The claim is published last on the
    real state ref, on `claim_branch` (the pull request's `branch` by default), its base
    the trunk tip before the merge, or, with `claim_after_the_merge`, the tip after the
    git step it names (an empty step is the merge commit itself). `forge_*` tell what the
    forge reports about the pull request, which a case may contradict with the remote."""
    push_lane_branch(clone, branch)
    claim_base = real_git(clone, "rev-parse", "main").stdout.strip()
    message = "\n\n".join((LANDING_TITLE, *(("\n".join(trailers),) if trailers else ())))
    merge_commit = merge_on_the_forge(remote, "main", branch, message, method)
    if claim_after_the_merge is not None:
        claim_base = (
            landed_from_another_clone(remote.parent, *claim_after_the_merge)
            if claim_after_the_merge
            else merge_commit
        )
    landing = landing_pull_request(
        body=pull_request_body,
        number=PULL_REQUEST,
        base_ref_name=forge_base,
        head_ref_name=branch,
        merged=forge_reports_merged,
        merge_commit=forge_merge_commit or merge_commit,
        title=LANDING_TITLE,
    )
    forge = serve_forge(monkeypatch, FakeForge(landings={PULL_REQUEST: landing}))
    intents = (
        ()
        if identity is None
        else (
            claim_intent(
                identity=identity,
                branch=claim_branch or branch,
                claim_id="landing",
                base=protocol.ObjectId(claim_base),
            ),
        )
    )
    publish_claims_from_a_second_clone(clone, remote, intents)
    return MergedPullRequest(forge, merge_commit, claim_base)


def state_ref_claims(clone: Path, remote: Path) -> dict[str, protocol.ActiveClaim]:
    return dict(store.peek_state(worktree=clone, remote=str(remote)).claims)
