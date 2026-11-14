"""How a board path entry (`lane_shared`, `dependency_paths`, `production_paths`) is read."""

import pytest

from aco import workboard


@pytest.mark.parametrize("key", ["lane_shared", "dependency_paths", "production_paths"])
@pytest.mark.parametrize("entry", ["frontend/*", "src/a?b.py"])
def test_board_configuration_keeps_a_path_entry_holding_a_glob_character(
    key: str, entry: str
) -> None:
    """Only a claim scope refuses `*` and `?`; a board path entry is compared as text."""
    config = workboard.parse_config(f'{key} = ["{entry}"]\n', workboard.CONFIG_PATH)

    assert entry in getattr(config, key)


@pytest.mark.parametrize(
    ("entry", "path"),
    [
        pytest.param("src/", "src/a?b.py", id="directory-covers-question-mark-name"),
        pytest.param("src/", "src/a*b.py", id="directory-covers-star-name"),
        pytest.param("src/a?b.py", "src/a?b.py", id="file-covers-itself"),
    ],
)
def test_a_path_entry_covers_a_tracked_file_named_with_a_glob_character(
    entry: str, path: str
) -> None:
    assert workboard.repository_path_entry_covers(entry, path)
