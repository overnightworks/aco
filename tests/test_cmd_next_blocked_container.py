"""`aco next` names a childless container with an open blocker under `SKIPPED`
instead of proposing it as `check_container` (NEXT-47)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from board_fixtures import block_dependency, complete_contract, container_with_children
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, assert_github_world, serve_forge

BLOCKER = 9


@pytest.fixture
def github_world(github_clone: Path, bare_remote: Path) -> None:
    assert_github_world(github_clone, bare_remote)


def serve_blocked_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """Container `#844`: closed children only and a `Next` that names work,
    blocked by `BLOCKER`."""
    container, children = container_with_children(
        844, closed=2, body=complete_contract("Scheibe D schneiden.")
    )
    freeze_cli_now(monkeypatch)
    serve_forge(
        monkeypatch,
        FakeForge(
            board_issues=(replace(container, blocked_by_count=1),),
            children={844: children},
            board_dependencies={844: (block_dependency(BLOCKER),)},
        ),
    )


@pytest.mark.usefixtures(github_world.__name__)
class TestNextBlockedContainer:
    def test_text_names_the_container_under_skipped_with_its_blocker(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-47 -- an open blocker beats NEXT-06, in text."""
        serve_blocked_container(monkeypatch)

        result = run_cli(["next"], capsys)

        lines = result.stdout.splitlines()
        assert result.status == 3
        assert lines[0] == "No actionable item."
        assert lines[-2:] == ["SKIPPED", f"#844: blocked by #{BLOCKER}"]

    def test_json_lists_the_container_as_skipped_with_its_blocker(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-47 -- an open blocker beats NEXT-06, in `--json`."""
        serve_blocked_container(monkeypatch)

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert payload["reason"] == "nothing_actionable"
        assert payload["skipped"] == [{"number": 844, "reason": f"blocked by #{BLOCKER}"}]
