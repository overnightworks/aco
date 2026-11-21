"""The board's address (`specs/serve.spec.md` ABRD-187, `specs/board.spec.md` BOARD-63)."""

from pathlib import Path

import pytest
from discovery_fixtures import BoardUnit, write_config

from aco import board_link, protocol

_TOKEN = "t" * 43


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        pytest.param(None, f"http://127.0.0.1:8765/#t={_TOKEN}", id="board"),
        pytest.param(
            board_link.CardLink("acme/widgets", 12, 3),
            f"http://127.0.0.1:8765/#t={_TOKEN}&c=acme/widgets/12/3",
            id="card",
        ),
        pytest.param(
            board_link.StepLink("acme/widgets", 12),
            f"http://127.0.0.1:8765/#t={_TOKEN}&s=acme/widgets/12",
            id="step",
        ),
    ],
)
def test_the_url_carries_the_token_and_the_selection_in_the_fragment(
    selection: board_link.CardLink | board_link.StepLink | None, expected: str
) -> None:
    assert board_link.board_url(8765, _TOKEN, selection) == expected


def test_the_configured_url_takes_port_and_token_from_the_configuration(
    board_unit: BoardUnit,
) -> None:
    assert board_link.configured_board_url(board_link.StepLink("acme/widgets", 7)) == (
        f"http://127.0.0.1:{board_unit.port}/#t={board_unit.token}&s=acme/widgets/7"
    )


def test_a_missing_board_port_is_refused_naming_the_config_file(config_file: Path) -> None:
    with pytest.raises(protocol.ClaimError, match=f"^board_port is not set in {config_file}$"):
        board_link.configured_board_url()


def test_a_missing_token_file_is_refused_naming_it(config_file: Path, tmp_path: Path) -> None:
    write_config(config_file, "board_port = 8765\n")
    token_path = tmp_path / "state" / "aco" / "board-token"

    with pytest.raises(protocol.ClaimError, match=f"^{token_path} does not exist"):
        board_link.configured_board_url()
    assert not token_path.exists()


def test_a_malformed_token_file_is_refused_naming_it(board_unit: BoardUnit) -> None:
    board_unit.token_file.write_text("short", encoding="utf-8")

    with pytest.raises(
        protocol.ClaimError, match=f"^{board_unit.token_file} holds no board token$"
    ):
        board_link.configured_board_url()


def test_the_optional_url_is_none_without_a_port(config_file: Path) -> None:
    assert board_link.configured_board_url_or_none() is None


def test_the_optional_url_is_none_with_a_port_but_no_token(config_file: Path) -> None:
    write_config(config_file, "board_port = 8765\n")

    assert board_link.configured_board_url_or_none() is None
