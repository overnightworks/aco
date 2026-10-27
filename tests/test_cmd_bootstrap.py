"""`aco bootstrap`, driven through the CLI against real git (`specs/bootstrap.spec.md`)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from cli_fixtures import (
    count_context_reads,
    fresh_observation,
    real_git,
    run_cli,
)
from store_fixtures import claim_intent, state_ref_listing, state_ref_tip

from aco import lineage_stamp, protocol, store

BOOTSTRAP_REPOSITORY = "example/agent-coordination"


@pytest.mark.parametrize(
    "origin_url",
    [
        pytest.param("git@github.com:example/agent-coordination.git", id="github-remote"),
        pytest.param("git@gitlab.com:other/repo.git", id="non-github-remote"),
    ],
)
def test_bootstrap_with_a_repo_prints_the_ref_commit_id_as_without_one(
    clone: Path,
    bare_remote: Path,
    origin_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BOOT-03 -- `--repo OWNER/REPO` against any canonical remote host."""
    real_git(clone, "config", f"url.{bare_remote}.insteadOf", origin_url)
    real_git(clone, "remote", "set-url", "origin", origin_url)

    with_repo = run_cli(["--repo", BOOTSTRAP_REPOSITORY, "bootstrap"], capsys)
    without_repo = run_cli(["bootstrap"], capsys)

    assert with_repo.stderr == ""
    assert without_repo.stderr == ""
    remote_state_commit = state_ref_tip(bare_remote)
    assert with_repo.expect_success() == f"{remote_state_commit}\n"
    assert without_repo.expect_success() == with_repo.stdout


@pytest.mark.parametrize(
    "extra_arguments",
    [
        pytest.param(["--ledger", "5"], id="ledger-flag"),
        pytest.param(["--json"], id="json-flag"),
        pytest.param(["extra"], id="positional"),
    ],
)
def test_bootstrap_refuses_an_argument_it_does_not_define_before_any_read(
    clone: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra_arguments: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: BOOT-02 -- an argument `bootstrap` does not define is refused."""
    reads = count_context_reads(monkeypatch)

    refused = run_cli(["bootstrap", *extra_arguments], capsys)

    assert refused.expect_refusal().endswith(
        f"aco: error: unrecognized arguments: {' '.join(extra_arguments)}\n"
    )
    assert reads.drain() == ({}, {}, {})


def test_bootstrap_refuses_an_unreachable_remote_on_stderr_alone(
    clone: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: BOOT-01 -- a store-level refusal prints only `ERROR: <sentence>`."""
    real_git(clone, "remote", "set-url", "origin", str(tmp_path / "missing.git"))

    with pytest.raises(protocol.ClaimError) as store_refusal:
        store.fetch_state(worktree=clone, remote="origin")
    assert str(store_refusal.value).startswith(
        "cannot reach origin refs/aco/state: auth or transport failure (ls-remote exited 128)"
    )

    refused = run_cli(["bootstrap"], capsys)

    assert refused.expect_refusal() == f"ERROR: {store_refusal.value}\n"
    assert refused.stdout == ""


def test_bootstrap_whose_creation_push_is_rejected_by_a_rival_leaves_the_rivals_state_untouched(
    clone: Path,
    bare_remote: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: CAS-01, CAS-66 -- a rival bootstraps and claims between this run's
    read of an absent ref and its push; the rejected push never writes over it."""
    rival_checkout = tmp_path / "rival"
    real_git(tmp_path, "clone", "-q", str(bare_remote), str(rival_checkout))
    remote = str(bare_remote)
    real_push = store.GitPushTransport.push
    rival_is_writing: list[bool] = []
    rival_tips: list[str | None] = []

    def push_after_the_rival_wrote(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if not rival_is_writing:
            rival_is_writing.append(True)
            store.bootstrap(worktree=rival_checkout, remote=remote)
            store.commit_transition(
                observed=fresh_observation(rival_checkout, remote),
                subject=store.ClaimTransitionSubject("claim issue 7", item="7"),
                intent=claim_intent(
                    identity=protocol.IssueIdentity(7), claim_id="rival-claim", operation_id="rival"
                ),
            )
            rival_tips.append(state_ref_tip(bare_remote))
        real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)

    monkeypatch.setattr(store.GitPushTransport, "push", push_after_the_rival_wrote)

    run = run_cli(["bootstrap"], capsys)

    [rival_tip] = rival_tips
    assert run.stderr == ""
    assert run.expect_success() == f"{rival_tip}\n"
    assert state_ref_tip(bare_remote) == rival_tip
    rival_state = store.fetch_state(worktree=rival_checkout, remote=remote)
    assert str(rival_state.tip) == rival_tip
    assert [str(claim.claim_id) for claim in rival_state.claims.values()] == ["rival-claim"]
    assert protocol.ClaimId("rival-claim") in rival_state.consumed_ids
    assert len(state_ref_listing(bare_remote)) > 1
    commit_count = subprocess.run(
        ["git", "--git-dir", remote, "rev-list", "--count", store.STATE_REF],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit_count == "2"


def _lose_the_response_of_the_first_push(monkeypatch: pytest.MonkeyPatch) -> None:
    real_push = store.GitPushTransport.push

    def push_landing_then_failing(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
        raise protocol.PushRejectedError("simulated lost response")

    monkeypatch.setattr(store.GitPushTransport, "push", push_landing_then_failing)


def _reject_the_first_push(monkeypatch: pytest.MonkeyPatch) -> None:
    real_push = store.GitPushTransport.push
    rejections: list[None] = []

    def push_rejected_once(
        transport: store.GitPushTransport,
        *,
        worktree: Path,
        remote: str,
        ref: str,
        new_oid: protocol.ObjectId,
    ) -> None:
        if rejections:
            real_push(transport, worktree=worktree, remote=remote, ref=ref, new_oid=new_oid)
            return
        rejections.append(None)
        raise protocol.PushRejectedError("simulated rejection")

    monkeypatch.setattr(store.GitPushTransport, "push", push_rejected_once)


@pytest.mark.parametrize(
    "arrange_fault",
    [
        pytest.param(_lose_the_response_of_the_first_push, id="lost-response"),
        pytest.param(_reject_the_first_push, id="rejected-while-absent"),
    ],
)
def test_bootstrap_prints_the_one_root_commit_after_a_push_retry(
    clone: Path,
    bare_remote: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arrange_fault: Callable[[pytest.MonkeyPatch], None],
) -> None:
    """Spec: CAS-66 -- a rejected creation push still leaves exactly one root."""
    arrange_fault(monkeypatch)

    run = run_cli(["bootstrap"], capsys)

    landed_tip = state_ref_tip(bare_remote)
    assert run.stderr == ""
    assert run.expect_success() == f"{landed_tip}\n"
    commit_count = subprocess.run(
        ["git", "--git-dir", str(bare_remote), "rev-list", "--count", store.STATE_REF],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert commit_count == "1"


def test_bootstrap_refuses_on_stderr_alone_when_its_lineage_stamp_cannot_be_written(
    clone: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spec: CAS-56 -- an accepted creation whose bookkeeping fails is uncertain."""

    def failing_stamp(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(lineage_stamp, "advance", failing_stamp)

    refused = run_cli(["bootstrap"], capsys)

    assert refused.expect_refusal() == "ERROR: disk full\n"
    assert refused.stdout == ""
