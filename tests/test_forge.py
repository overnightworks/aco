import pytest

from aco import forge


@pytest.mark.parametrize(
    ("pin", "names_head"),
    [("a1b2c3d", True), ("a1b2c3d4e5f6", True), ("b2c3d4e", False)],
)
def test_a_head_pin_names_the_head_it_is_a_prefix_of(pin: str, names_head: bool) -> None:
    assert forge.pin_names_head("a1b2c3d4e5f6", pin) is names_head
