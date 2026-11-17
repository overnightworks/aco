"""The `step` table of an item's block (`specs/body-block.spec.md`): what refuses it,
how it reads and how it renders."""

import tomllib

import pytest

from aco import item_step


def _table(**changes: object) -> dict[str, object]:
    return {"purpose": "Why.", "actions": "Do this.", "expected": "See that.", **changes}


def test_an_absent_step_table_has_no_defects_and_no_card() -> None:
    assert item_step.step_defects({}) == []
    assert item_step.parse_step({}) is None
    assert item_step.render_step({}) == []


def test_a_valid_table_reads_as_a_stripped_card_with_an_optional_answer() -> None:
    data = {"step": _table(purpose=" Why.\n", answer=" Say. ")}

    assert item_step.step_defects(data) == []
    assert item_step.parse_step(data) == item_step.StepCard("Why.", "Do this.", "See that.", "Say.")
    assert item_step.parse_step({"step": _table()}) == item_step.StepCard(
        "Why.", "Do this.", "See that.", None
    )


@pytest.mark.parametrize(
    ("data", "field"),
    [
        pytest.param({"step": "text"}, "step", id="not-a-table"),
        pytest.param({"step": {"actions": "a", "expected": "e"}}, "step.purpose", id="no-purpose"),
        pytest.param({"step": _table(actions=" \n")}, "step.actions", id="blank-actions"),
        pytest.param({"step": _table(expected=3)}, "step.expected", id="expected-integer"),
        pytest.param({"step": _table(answer="")}, "step.answer", id="blank-answer"),
        pytest.param({"step": _table(extra="x")}, "step.extra", id="unknown-key"),
    ],
)
def test_a_defective_table_names_the_field(data: dict[str, object], field: str) -> None:
    assert [name for name, _ in item_step.step_defects(data)] == [field]


@pytest.mark.parametrize(
    "table",
    [
        _table(),
        _table(answer="Report the key id, because it proves the rotation."),
        _table(actions='cd repo\n./rotate "$KEY" \\\n  && echo "done"\n\tindented'),
        _table(purpose="```fence```", expected="~~~\nline"),
    ],
    ids=["short", "answer", "multi-line-actions", "fences"],
)
def test_a_card_renders_and_reads_back_unchanged(table: dict[str, object]) -> None:
    text = "\n".join(item_step.render_step({"step": table}))

    assert tomllib.loads(text)["step"] == table
