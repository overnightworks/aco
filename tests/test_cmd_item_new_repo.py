"""`aco --repo OWNER/NAME item new` from one checkout, into another repository
the machine's discovery finds, on real checkouts and the real state ref. The
forge is the only fake."""

import json
from pathlib import Path

import pytest
from board_fixtures import REPOSITORY, complete_contract
from claim_worktrees import make_stand_in
from cli_fixtures import init_bare_repository, run_cli
from discovery_fixtures import configure_root, discovered_checkout, isolate_config_file
from github_fixtures import FakeForge
from store_fixtures import path_without_gh, push_item_tree, state_ref_listing, state_ref_tip

from aco import forge, github

OTHER = "example/other"
OTHER_URL = f"https://github.com/{OTHER}"
STATE_REF_CONFIG = 'storage = "state-ref"\n'
BODY = complete_contract("Ship it.")


@pytest.fixture(autouse=True)
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_config_file(tmp_path, monkeypatch)


@pytest.fixture
def root(tmp_path: Path, config_file: Path) -> Path:
    return configure_root(tmp_path, config_file)


@pytest.fixture
def other_bare(tmp_path: Path) -> Path:
    return init_bare_repository(tmp_path / "other.git")


@pytest.fixture
def own_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, github_clone: Path, bare_remote: Path
) -> Path:
    """The checkout the command is made from, a GitHub-pinned repository
    outside the configured root."""
    return make_stand_in(monkeypatch, tmp_path, github_clone, bare_remote, ())(
        linked=False
    ).directory


@pytest.fixture
def built_for(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, FakeForge]]:
    """Each GitHub forge a run built, as the repository it targeted and the
    fake that answered."""
    built: list[tuple[str, FakeForge]] = []

    def build(repository: forge.RepositoryId) -> FakeForge:
        fake = FakeForge()
        built.append((repository.path, fake))
        return fake

    monkeypatch.setattr(github, "GitHubForge", build)
    return built


def test_item_new_opens_the_issue_in_the_discovered_repository_under_github(
    root: Path,
    other_bare: Path,
    own_checkout: Path,
    built_for: list[tuple[str, FakeForge]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-67. The item is created under the other repository's own
    forge target, not the checkout's."""
    discovered_checkout(root / "other", OTHER_URL, other_bare, "")

    result = run_cli(["--repo", OTHER, "item", "new", "--title", "Friction"], capsys, stdin=BODY)

    assert result.status == 0
    assert [(target, len(fake.created_issues)) for target, fake in built_for] == [(OTHER, 1)]


def test_item_new_writes_the_state_ref_item_of_the_discovered_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    root: Path,
    other_bare: Path,
    bare_remote: Path,
    own_checkout: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-67, PIN-57. A state-ref repository keeps its own storage and
    its own remote's state ref takes the item."""
    other = discovered_checkout(
        root / "other", f"https://forge.test/{OTHER}", other_bare, STATE_REF_CONFIG
    )
    push_item_tree(other_bare, other, {})
    monkeypatch.setenv("PATH", path_without_gh(tmp_path))
    own_tip = state_ref_tip(bare_remote)
    seeded = state_ref_listing(other_bare)

    result = run_cli(
        ["--repo", OTHER, "item", "new", "--title", "Friction", "--json"], capsys, stdin=BODY
    )

    assert result.status == 0
    assert json.loads(result.stdout)["reason"] == "created"
    assert len(state_ref_listing(other_bare)) == len(seeded) + 1
    assert state_ref_tip(bare_remote) == own_tip


def test_item_new_in_an_undiscovered_repository_refuses_by_name_and_writes_nothing(
    root: Path,
    other_bare: Path,
    own_checkout: Path,
    built_for: list[tuple[str, FakeForge]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-68."""
    discovered_checkout(root / "other", OTHER_URL, other_bare, "")

    result = run_cli(
        ["--repo", "example/absent", "item", "new", "--title", "Friction"], capsys, stdin=BODY
    )

    assert (result.status, result.stderr) == (2, "ERROR: no repository example/absent found\n")
    assert built_for == []


def test_item_new_refuses_a_discovered_checkout_whose_remote_is_another_repository(
    root: Path,
    other_bare: Path,
    own_checkout: Path,
    built_for: list[tuple[str, FakeForge]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-67, PIN-53. The target is the resolved checkout's own
    remote; a label a checkout does not carry is no repository."""
    discovered_checkout(root / "other", OTHER_URL, other_bare, "")

    result = run_cli(
        ["--repo", "example/renamed", "item", "new", "--title", "Friction"], capsys, stdin=BODY
    )

    assert result.status == 2
    assert built_for == []


def test_item_new_naming_the_checkouts_own_repository_needs_no_discovery(
    own_checkout: Path,
    built_for: list[tuple[str, FakeForge]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Spec: ITEM-69. No root holds this checkout, and it still creates the
    item under its own repository."""
    result = run_cli(
        ["--repo", REPOSITORY, "item", "new", "--title", "Friction"], capsys, stdin=BODY
    )

    assert result.status == 0
    assert [(target, len(fake.created_issues)) for target, fake in built_for] == [(REPOSITORY, 1)]
