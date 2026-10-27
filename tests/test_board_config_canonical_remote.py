from __future__ import annotations

from pathlib import Path

import pytest

from aco import workboard
from aco.protocol import ClaimError


def test_canonical_remote_defaults_to_origin_and_takes_a_named_one_as_written(
    tmp_path: Path,
) -> None:
    """PIN-50."""
    config_path = tmp_path / "board.toml"
    assert workboard.load_config(config_path).canonical_remote == "origin"

    config_path.write_text('canonical_remote = "upstream"\n')
    assert workboard.load_config(config_path).canonical_remote == "upstream"


@pytest.mark.parametrize(
    "toml_value",
    ['""', "true", '" origin"', '"-x"', '"--upload-pack=./p"'],
)
def test_canonical_remote_that_names_no_plain_remote_refuses(
    tmp_path: Path, toml_value: str
) -> None:
    """PIN-51."""
    config_path = tmp_path / "board.toml"
    config_path.write_text(f"canonical_remote = {toml_value}\n")
    expected = (
        f"board configuration {config_path} canonical_remote must be a non-empty "
        "remote name not starting with '-'"
    )
    with pytest.raises(ClaimError) as refusal:
        workboard.load_config(config_path)
    assert str(refusal.value) == expected
