"""The block's `step` table through the body codec (`specs/body-block.spec.md`): a
defective one makes the body malformed and a rewrite of the block keeps a valid one."""

from board_fixtures import MINIMAL_BLOCK_TOML, block_body, complete_contract

from aco import body


def _table(**changes: object) -> dict[str, object]:
    return {"purpose": "Why.", "actions": "Do\nthis.", "expected": "See that.", **changes}


def test_a_body_with_a_valid_step_table_is_valid() -> None:
    parsed = body.parse_body(complete_contract("Next.", step=_table()))

    assert parsed.read_state is body.BodyReadState.VALID


def test_a_body_with_a_defective_step_table_is_refused_naming_the_field() -> None:
    parsed = body.parse_body(complete_contract("Next.", step=_table(purpose=" ")))

    assert parsed.read_state is body.BodyReadState.MALFORMED
    assert [defect.field for defect in parsed.contract.defects] == ["step.purpose"]


def test_a_body_with_an_unknown_block_key_in_the_step_table_is_refused() -> None:
    held = block_body(
        MINIMAL_BLOCK_TOML
        + '[step]\npurpose = "a"\nactions = "b"\nexpected = "c"\ncolour = "red"\n'
    )
    parsed = body.parse_body(held)

    assert [defect.field for defect in parsed.contract.defects] == ["step.colour"]


def test_rewriting_the_block_keeps_the_step_table() -> None:
    held = complete_contract("Next.", step=_table(answer="Say."))
    located = body.locate_block(held)

    rewritten = body.replace_block(held, located, {**located.data, "next": "Other."})

    assert body.locate_block(rewritten).data == {**located.data, "next": "Other."}
