"""The `runs/` directory of `refs/aco/state` on real git against a real bare remote: which entries
the tree reader accepts, which it refuses, that no other transition drops or rewrites a runs
file, that the status archive never reads its content, and that a release and a landing remove
the claim's file in their own commit (`specs/ref-store-cas.spec.md`)."""

import re
from pathlib import Path

import pytest
from cli_fixtures import fresh_observation, real_git, set_git_identity
from store_fixtures import (
    blob,
    claim_intent,
    push_raw_state_tree,
    raw_tree,
    state_ref_listing,
    unrelated_racer_commit,
)

from aco import protocol, store

CLAIM_ID = "a1"
OTHER_CLAIM_ID = "orphaned"
RUNS_FILE = b'{"version": 1, "runs": []}\n'
ITEM_ID = "aco-000001"


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    set_git_identity(monkeypatch)


def holder_sentence(holder: str) -> str:
    return f"only the holder may write ({holder})"


def runs_write(
    worktree: Path,
    content: bytes,
    *,
    claim_id: str = CLAIM_ID,
    expected: protocol.ObjectId | None = None,
) -> protocol.RunsWriteIntent:
    return protocol.RunsWriteIntent(
        claim_id=protocol.ClaimId(claim_id),
        agent="Ada",
        expected=expected,
        new_oid=store.hash_blob(worktree, content),
        operation_id=f"op-runs-{claim_id}-{len(content)}",
        holder_refusal=holder_sentence,
        stale_refusal="the runs were written since they were read",
    )


def commit(worktree: Path, remote: Path, subject: str, intent: protocol.ClaimTransitionIntent):
    return store.commit_transition(
        observed=fresh_observation(worktree, remote),
        subject=store.TransitionSubject(subject),
        intent=intent,
    )


def claimed_with_runs(worktree: Path, remote: Path, content: bytes = RUNS_FILE) -> None:
    """Issue 42 claimed by Ada, then one runs file written under its claim id."""
    store.bootstrap(worktree=worktree, remote=str(remote))
    commit(worktree, remote, "claim issue 42", claim_intent())
    commit(worktree, remote, "lane-record issue 42", runs_write(worktree, content))


def tree_listing(remote: Path) -> dict[str, str]:
    return {path.decode(): header.decode() for path, header in state_ref_listing(remote).items()}


def top_level_entries(remote: Path) -> set[str]:
    return {path.split("/", 1)[0] for path in tree_listing(remote)}


def release_intent() -> protocol.ReleaseIntent:
    return protocol.ReleaseIntent(
        claim_id=protocol.ClaimId(CLAIM_ID),
        agent="Ada",
        role="builder",
        outcome=protocol.AbandonedRelease("done"),
        operation_id="op-release",
    )


def push_state_with_runs_entries(
    remote: Path, worktree: Path, runs_entries: list[tuple[str, str, str, str]]
) -> None:
    """A state tree of `schema.toml` and a `runs/` directory holding exactly `runs_entries`."""
    schema = blob(worktree, protocol.serialize_empty_schema_toml().encode())
    runs_tree = raw_tree(worktree, runs_entries)
    push_raw_state_tree(
        remote,
        worktree,
        [
            ("100644", "blob", schema, store.SCHEMA_TOML_FILENAME),
            ("040000", "tree", runs_tree, "runs"),
        ],
    )


def test_a_runs_directory_of_run_files_is_accepted_and_names_each_claims_blob(
    bare_remote: Path, worktree: Path
) -> None:
    first = blob(worktree, b"first")
    second = blob(worktree, b"second")
    push_state_with_runs_entries(
        bare_remote,
        worktree,
        [("100644", "blob", first, "a1.json"), ("100644", "blob", second, "c-2.v1.json")],
    )

    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))

    assert dict(state.runs) == {"a1": first, "c-2.v1": second}


def test_the_content_of_a_runs_file_is_never_read_by_the_state_read(
    bare_remote: Path, worktree: Path
) -> None:
    push_state_with_runs_entries(
        bare_remote,
        worktree,
        [("100644", "blob", blob(worktree, b"\xff not json at all"), "a1.json")],
    )

    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))

    assert set(state.runs) == {"a1"}


@pytest.mark.parametrize(
    "mode, kind, name",
    [
        pytest.param("100644", "blob", "notes.txt", id="no-json-suffix"),
        pytest.param("100644", "blob", "a1", id="no-suffix-at-all"),
        pytest.param("100644", "blob", ".json", id="no-claim-id"),
        pytest.param("100644", "blob", "-a.json", id="a-claim-id-may-not-start-with-a-dash"),
        pytest.param("100644", "blob", "a b.json", id="a-name-with-a-space"),
        pytest.param("120000", "blob", "a1.json", id="a-symlink"),
        pytest.param("040000", "tree", "a1.json", id="a-directory"),
    ],
)
def test_a_runs_entry_that_is_no_run_file_refuses_the_read_naming_it(
    bare_remote: Path, worktree: Path, mode: str, kind: str, name: str
) -> None:
    entry_oid = blob(worktree, b"x") if kind == "blob" else raw_tree(worktree, [])
    push_state_with_runs_entries(bare_remote, worktree, [(mode, kind, entry_oid, name)])

    with pytest.raises(
        protocol.MalformedStateTreeError,
        match=rf"runs/{re.escape(name)} at [0-9a-f]{{40}} is not a run file",
    ):
        store.fetch_state(worktree=worktree, remote=str(bare_remote))


def test_a_runs_entry_that_is_not_a_directory_refuses_the_read(
    bare_remote: Path, worktree: Path
) -> None:
    schema = blob(worktree, protocol.serialize_empty_schema_toml().encode())
    push_raw_state_tree(
        bare_remote,
        worktree,
        [
            ("100644", "blob", schema, store.SCHEMA_TOML_FILENAME),
            ("100644", "blob", blob(worktree, b"x"), "runs"),
        ],
    )

    with pytest.raises(protocol.MalformedStateTreeError, match=r"runs at .* is not a directory"):
        store.fetch_state(worktree=worktree, remote=str(bare_remote))


def test_a_runs_write_stores_the_blob_under_the_claim_id_and_reads_back(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)

    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))

    assert dict(state.runs) == {CLAIM_ID: store.hash_blob(worktree, RUNS_FILE)}
    assert tree_listing(bare_remote)[f"runs/{CLAIM_ID}.json"].startswith("100644 blob ")


def test_a_second_runs_write_replaces_the_blob_and_keeps_one_file(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)
    first = store.fetch_state(worktree=worktree, remote=str(bare_remote)).runs[CLAIM_ID]
    changed = b'{"version": 1, "runs": [], "again": true}\n'

    commit(
        worktree, bare_remote, "lane-record issue 42", runs_write(worktree, changed, expected=first)
    )

    state = store.fetch_state(worktree=worktree, remote=str(bare_remote))
    assert dict(state.runs) == {CLAIM_ID: store.hash_blob(worktree, changed)}
    assert [path for path in tree_listing(bare_remote) if path.startswith("runs/")] == [
        f"runs/{CLAIM_ID}.json"
    ]


def test_an_unrelated_write_carries_every_runs_file_unchanged(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)
    before = {path: header for path, header in tree_listing(bare_remote).items() if "runs/" in path}

    commit(
        worktree,
        bare_remote,
        "claim issue 7",
        claim_intent(
            identity=protocol.IssueIdentity(7),
            branch="claude/issue-7-cut",
            scope=("src/other.py",),
            claim_id="b2",
            operation_id="op-other",
        ),
    )

    after = {path: header for path, header in tree_listing(bare_remote).items() if "runs/" in path}
    assert after == before != {}


def test_an_unrelated_racer_does_not_lose_the_runs_write_it_raced(
    bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    commit(worktree, bare_remote, "claim issue 42", claim_intent())
    observed = fresh_observation(worktree, bare_remote)
    unrelated_racer_commit(worktree, bare_remote)

    store.commit_transition(
        observed=observed,
        subject=store.TransitionSubject("lane-record issue 42"),
        intent=runs_write(worktree, RUNS_FILE),
    )

    assert f"runs/{CLAIM_ID}.json" in tree_listing(bare_remote)


def test_a_runs_file_of_a_claim_id_with_no_live_claim_is_carried_by_every_write(
    bare_remote: Path, worktree: Path
) -> None:
    schema = blob(worktree, protocol.serialize_empty_schema_toml().encode())
    orphan = blob(worktree, b"orphan")
    runs_tree = raw_tree(worktree, [("100644", "blob", orphan, f"{OTHER_CLAIM_ID}.json")])
    push_raw_state_tree(
        bare_remote,
        worktree,
        [
            ("100644", "blob", schema, store.SCHEMA_TOML_FILENAME),
            ("040000", "tree", runs_tree, "runs"),
        ],
    )

    commit(worktree, bare_remote, "claim issue 42", claim_intent())
    commit(worktree, bare_remote, "release issue 42", release_intent())

    assert tree_listing(bare_remote)[f"runs/{OTHER_CLAIM_ID}.json"] == f"100644 blob {orphan}"


def test_a_release_removes_the_claims_runs_file_in_its_own_commit_and_runs_goes_with_the_last(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)
    assert "runs" in top_level_entries(bare_remote)

    released = commit(worktree, bare_remote, "release issue 42", release_intent())

    assert dict(released.runs) == {}
    assert "runs" not in top_level_entries(bare_remote)
    message = real_git(bare_remote, "log", "-1", "--format=%B", store.STATE_REF).stdout
    assert message.startswith("release issue 42")


def test_a_release_keeps_the_runs_files_of_other_claim_ids(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)
    commit(
        worktree,
        bare_remote,
        "claim issue 7",
        claim_intent(
            identity=protocol.IssueIdentity(7),
            branch="claude/issue-7-cut",
            scope=("src/other.py",),
            claim_id=OTHER_CLAIM_ID,
            operation_id="op-other",
        ),
    )
    commit(
        worktree,
        bare_remote,
        "lane-record issue 7",
        runs_write(worktree, b"other runs", claim_id=OTHER_CLAIM_ID),
    )

    commit(worktree, bare_remote, "release issue 42", release_intent())

    assert [path for path in tree_listing(bare_remote) if path.startswith("runs/")] == [
        f"runs/{OTHER_CLAIM_ID}.json"
    ]


def test_a_landing_removes_the_claims_runs_file_in_its_own_commit_and_runs_goes_with_the_last(
    bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    item_oid = protocol.ObjectId(store.hash_blob(worktree, b"item open"))
    commit(
        worktree,
        bare_remote,
        "write item aco-000001",
        protocol.ItemWriteIntent(
            item_id=ITEM_ID, expected=None, new_oid=item_oid, operation_id="op-item"
        ),
    )
    commit(worktree, bare_remote, "claim issue 42", claim_intent())
    commit(worktree, bare_remote, "lane-record issue 42", runs_write(worktree, RUNS_FILE))
    landing = protocol.LandingIntent(
        item_id=ITEM_ID,
        item_expected=item_oid,
        item_new_oid=protocol.ObjectId(store.hash_blob(worktree, b"item closed")),
        claim_id=protocol.ClaimId(CLAIM_ID),
        agent="Ada",
        role="builder",
        outcome=protocol.LandedRelease(protocol.ObjectId("4" * 40)),
        operation_id="op-landing",
    )

    commit(worktree, bare_remote, "release issue 42", landing)

    assert "runs" not in top_level_entries(bare_remote)
    assert f"items/{ITEM_ID}.md" in tree_listing(bare_remote)


def test_a_runs_write_commit_names_its_intent_and_claim_without_any_lane_trailer(
    bare_remote: Path, worktree: Path
) -> None:
    claimed_with_runs(worktree, bare_remote)

    message = real_git(bare_remote, "log", "-1", "--format=%B", store.STATE_REF).stdout

    assert f"claim_id: {CLAIM_ID}\nintent: lane_record\n" in message
    assert "\nlane_" not in message


def test_the_holder_refusal_of_a_runs_write_by_another_agent_names_no_write(
    bare_remote: Path, worktree: Path
) -> None:
    store.bootstrap(worktree=worktree, remote=str(bare_remote))
    commit(worktree, bare_remote, "claim issue 42", claim_intent())
    tip_before = store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip
    intruder = protocol.RunsWriteIntent(
        claim_id=protocol.ClaimId(CLAIM_ID),
        agent="Bea",
        expected=None,
        new_oid=store.hash_blob(worktree, RUNS_FILE),
        operation_id="op-intruder",
        holder_refusal="{} may not write".format,
        stale_refusal="stale",
    )

    with pytest.raises(protocol.ClaimUnavailableError, match="Ada may not write"):
        commit(worktree, bare_remote, "lane-record issue 42", intruder)

    assert store.fetch_state(worktree=worktree, remote=str(bare_remote)).tip == tip_before
