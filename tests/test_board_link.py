"""The board's address (`specs/serve.spec.md` ABRD-187, `specs/board.spec.md` BOARD-63)."""

from pathlib import Path

import pytest

from aco import board_link, protocol

_TOKEN = "t" * 43


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "config" / "aco" / "config.toml"


@pytest.fixture
def token_file(config_file: Path) -> Path:
    path = config_file.parents[2] / "state" / "aco" / "board-token"
    path.parent.mkdir(parents=True)
    path.write_text(_TOKEN, encoding="utf-8")
    return path


def _configure_port(config_file: Path, port: int) -> None:
    config_file.parent.mkdir(parents=True)
    config_file.write_text(f"board_port = {port}\n", encoding="utf-8")


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
    config_file: Path, token_file: Path
) -> None:
    _configure_port(config_file, 8765)

    assert board_link.configured_board_url(board_link.StepLink("acme/widgets", 7)) == (
        f"http://127.0.0.1:8765/#t={_TOKEN}&s=acme/widgets/7"
    )


def test_a_missing_board_port_is_refused_naming_the_config_file(
    config_file: Path, token_file: Path
) -> None:
    with pytest.raises(protocol.ClaimError, match=f"^board_port is not set in {config_file}$"):
        board_link.configured_board_url()


def test_a_missing_token_file_is_refused_naming_it(config_file: Path) -> None:
    _configure_port(config_file, 8765)
    token_path = config_file.parents[2] / "state" / "aco" / "board-token"

    with pytest.raises(protocol.ClaimError, match=f"^{token_path} does not exist"):
        board_link.configured_board_url()
    assert not token_path.exists()


def test_a_malformed_token_file_is_refused_naming_it(config_file: Path, token_file: Path) -> None:
    _configure_port(config_file, 8765)
    token_file.write_text("short", encoding="utf-8")

    with pytest.raises(protocol.ClaimError, match=f"^{token_file} holds no board token$"):
        board_link.configured_board_url()


@pytest.mark.parametrize("configured", [False, True], ids=["no-port", "port-but-no-token"])
def test_the_optional_url_is_none_where_the_configuration_gives_none(
    config_file: Path, configured: bool
) -> None:
    if configured:
        _configure_port(config_file, 8765)

    assert board_link.configured_board_url_or_none() is None
