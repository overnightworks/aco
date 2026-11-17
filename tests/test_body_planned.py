"""The `planned_at_first_cut` stamp of an item's `aco` block (src/aco/body_planned.py)."""

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body

from aco import body
from aco.body import BodyReadState, ContractDefect

STAMP_DEFECT = ContractDefect(
    "planned_at_first_cut", "planned_at_first_cut must be a positive integer"
)


def _parsed(extra: str) -> body.ParsedBody:
    return body.parse_body(block_body(MINIMAL_BLOCK_TOML + extra))


@pytest.mark.parametrize("extra", ["", "planned_at_first_cut = 1\n", "planned_at_first_cut = 7\n"])
def test_an_absent_or_positive_integer_stamp_is_valid(extra: str) -> None:
    """Spec: BODY-118, BODY-119"""
    assert _parsed(extra).read_state is BodyReadState.VALID


@pytest.mark.parametrize("value", ["0", "-1", "true", '"3"', "1.5", "[3]"])
def test_any_other_stamp_is_malformed(value: str) -> None:
    """Spec: BODY-120"""
    parsed = _parsed(f"planned_at_first_cut = {value}\n")

    assert parsed.contract.defects == (STAMP_DEFECT,)
    assert parsed.read_state is BodyReadState.MALFORMED


def test_a_rewrite_keeps_the_stamp_ahead_of_the_slice_rows() -> None:
    """Spec: BODY-121"""
    toml_text = (
        MINIMAL_BLOCK_TOML + 'planned_at_first_cut = 3\n\n[[slice]]\nindex = 1\ntitle = "A"\n'
    )
    located = body.locate_block(block_body(toml_text))

    rendered = body.render_block(located.data)

    assert rendered.index("planned_at_first_cut = 3\n") < rendered.index("[[slice]]")
