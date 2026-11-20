"""`aco next` names a childless, row-less container with an open blocker as a
closable container, whatever its `Next` line says (NEXT-07)."""

import json
from dataclasses import replace

import pytest
from board_fixtures import block_dependency, complete_contract, container_with_children
from cli_fixtures import freeze_cli_now, run_cli
from github_fixtures import FakeForge, serve_forge

BLOCKER = 9


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


@pytest.mark.usefixtures("github_world")
class TestNextBlockedContainer:
    def test_text_closes_the_container_despite_its_blocker(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-07 -- an open blocker keeps a row-less container closable, in text."""
        serve_blocked_container(monkeypatch)

        result = run_cli(["next"], capsys)

        assert result.status == 0
        assert result.stdout == (
            "close_container #844: 2/2 children closed, no uncut row\n"
            "parallel: none\nscope unknown: none\nclose: #844\n"
        )

    def test_json_lists_the_container_under_close_despite_its_blocker(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Spec: NEXT-07 -- an open blocker keeps a row-less container closable, in `--json`."""
        serve_blocked_container(monkeypatch)

        payload = json.loads(run_cli(["next", "--json"], capsys).stdout)

        assert payload["reason"] == "close_container"
        assert payload["close"] == [844]
        assert payload["skipped"] == []
