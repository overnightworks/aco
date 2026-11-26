"""The `step` table of an item's block (`specs/body-block.spec.md`): what refuses it,
how it reads and how it renders, in the paste form and in the form stored before it."""

import tomllib

import pytest

from aco import item_step


def _table(**changes: object) -> dict[str, object]:
    return {"purpose": "Why.", "paste": "make rotate", "expected": "See that.", **changes}


def _old_table(**changes: object) -> dict[str, object]:
    return {"purpose": "Why.", "actions": "Do this.", "expected": "See that.", **changes}


def test_an_absent_step_table_has_no_defects_and_no_card() -> None:
    assert item_step.step_defects({}) == []
    assert item_step.parse_step({}) is None
    assert item_step.render_step({}) == []


def test_a_paste_table_reads_as_a_stripped_card() -> None:
    """Spec: BODY-126"""
    data = {"step": _table(purpose=" Why.\n", paste="\n  make rotate\n")}

    assert item_step.step_defects(data) == []
    assert item_step.parse_step(data) == item_step.StepCard("Why.", "make rotate", "See that.")


@pytest.mark.parametrize(
    ("table", "card"),
    [
        pytest.param(
            _old_table(purpose=" Why.\n"),
            item_step.OldStepCard("Why.", "Do this.", "See that.", None),
            id="without-answer",
        ),
        pytest.param(
            _old_table(answer=" Say. "),
            item_step.OldStepCard("Why.", "Do this.", "See that.", "Say."),
            id="with-answer",
        ),
    ],
)
def test_an_actions_table_reads_as_an_old_card(
    table: dict[str, object], card: item_step.OldStepCard
) -> None:
    """Spec: BODY-123"""
    data = {"step": table}

    assert item_step.step_defects(data) == []
    assert item_step.parse_step(data) == card


@pytest.mark.parametrize(
    ("data", "field"),
    [
        pytest.param({"step": "text"}, "step", id="not-a-table"),
        pytest.param({"step": {"paste": "a", "expected": "e"}}, "step.purpose", id="no-purpose"),
        pytest.param({"step": {"actions": "a", "expected": "e"}}, "step.purpose", id="old-purpose"),
        pytest.param({"step": _table(expected=3)}, "step.expected", id="expected-integer"),
        pytest.param({"step": _old_table(answer="")}, "step.answer", id="blank-answer"),
    ],
)
def test_a_defective_table_names_the_field(data: dict[str, object], field: str) -> None:
    """Spec: BODY-124, BODY-127"""
    assert [name for name, _ in item_step.step_defects(data)] == [field]


def test_a_paste_that_breaks_the_tool_rules_is_still_a_valid_table() -> None:
    """Spec: BODY-126"""
    data = {"step": _table(paste="make a\nmake b; make c")}

    assert item_step.step_defects(data) == []


@pytest.mark.parametrize(
    "table",
    [
        _table(),
        _table(paste="cd repo && ./rotate"),
        _table(paste='cd repo\n./rotate "$KEY" \\\n  && echo "done"\n\tindented'),
        _old_table(),
        _old_table(answer="Report the key id, because it proves the rotation."),
        _old_table(actions='cd repo\n./rotate "$KEY" \\\n  && echo "done"\n\tindented'),
        _old_table(purpose="```fence```", expected="~~~\nline"),
    ],
    ids=[
        "paste",
        "paste-with-cd",
        "paste-multi-line",
        "old",
        "old-answer",
        "old-multi-line-actions",
        "old-fences",
    ],
)
def test_a_card_renders_and_reads_back_key_for_key(table: dict[str, object]) -> None:
    """Spec: BODY-128"""
    text = "\n".join(item_step.render_step({"step": table}))

    assert tomllib.loads(text)["step"] == table


@pytest.mark.parametrize(
    ("card", "table"),
    [
        pytest.param(
            item_step.StepCard("Why.", "make rotate", "See that."), _table(), id="paste-card"
        ),
        pytest.param(
            item_step.OldStepCard("Why.", "Do this.", "See that.", "Say."),
            _old_table(answer="Say."),
            id="old-card-with-answer",
        ),
        pytest.param(
            item_step.OldStepCard("Why.", "Do this.", "See that.", None),
            _old_table(),
            id="old-card-without-answer",
        ),
    ],
)
def test_a_card_is_stored_with_the_keys_of_its_form_in_order(
    card: item_step.StoredStepCard, table: dict[str, object]
) -> None:
    assert list(item_step.step_table(card).items()) == list(table.items())
