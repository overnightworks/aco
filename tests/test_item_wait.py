"""The block's one typed `wait` (`specs/body-block.spec.md`): reading, refusing and writing it."""

from datetime import date

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body

from aco import body, item_wait

SINCE = date(2026, 11, 1)
DEADLINE = date(2026, 12, 1)


def _parsed(wait_line: str) -> body.ParsedBody:
    return body.parse_body(block_body(MINIMAL_BLOCK_TOML + wait_line + "\n"))


def _printed_defects(wait_line: str) -> list[str]:
    parsed = _parsed(wait_line)
    assert parsed.read_state is body.BodyReadState.MALFORMED
    return [body.body_defect_text(defect) for defect in parsed.contract.defects]


@pytest.mark.parametrize(
    ("wait_line", "expected"),
    [
        pytest.param(
            'wait = { operator = "Rotate the key.", since = 2026-11-01 }',
            item_wait.OperatorWait("Rotate the key.", SINCE),
            id="operator",
        ),
        pytest.param(
            "wait = { until = 2026-12-01, since = 2026-11-01 }",
            item_wait.UntilWait(DEADLINE, SINCE),
            id="until",
        ),
        pytest.param(
            'wait = { trigger = "A second machine exists.", since = 2026-11-01 }',
            item_wait.TriggerWait("A second machine exists.", SINCE),
            id="trigger",
        ),
        pytest.param("", None, id="absent"),
    ],
)
def test_a_block_reads_its_one_wait(wait_line: str, expected: item_wait.ItemWait | None) -> None:
    parsed = _parsed(wait_line)

    assert parsed.read_state is body.BodyReadState.VALID
    assert parsed.wait == expected


@pytest.mark.parametrize(
    ("wait_line", "printed"),
    [
        pytest.param(
            'wait = "soon"',
            "body malformed: wait: wait must be a table",
            id="not-a-table",
        ),
        pytest.param(
            "wait = { since = 2026-11-01 }",
            "body malformed: wait: wait must name exactly one of operator, until, trigger",
            id="no-kind",
        ),
        pytest.param(
            'wait = { operator = "A", trigger = "B", since = 2026-11-01 }',
            "body malformed: wait: wait must name exactly one of operator, until, trigger",
            id="two-kinds",
        ),
        pytest.param(
            'wait = { operator = " ", since = 2026-11-01 }',
            "body malformed: wait.operator: wait.operator must be a non-empty string",
            id="blank-operator",
        ),
        pytest.param(
            "wait = { trigger = 3, since = 2026-11-01 }",
            "body malformed: wait.trigger: wait.trigger must be a non-empty string",
            id="trigger-not-a-string",
        ),
        pytest.param(
            'wait = { until = "2026-12-01", since = 2026-11-01 }',
            "body malformed: wait.until: wait.until must be a TOML local date",
            id="until-not-a-date",
        ),
        pytest.param(
            'wait = { operator = "A" }',
            "body malformed: wait.since: wait.since must be a TOML local date",
            id="since-missing",
        ),
        pytest.param(
            'wait = { operator = "A", since = "2026-11-01" }',
            "body malformed: wait.since: wait.since must be a TOML local date",
            id="since-not-a-date",
        ),
        pytest.param(
            'wait = { operator = "A", since = 2026-11-01, odd = 1 }',
            "body malformed: wait.odd: unknown key wait.odd",
            id="unknown-key",
        ),
    ],
)
def test_a_malformed_wait_is_a_body_defect(wait_line: str, printed: str) -> None:
    assert _printed_defects(wait_line) == [printed]


def test_the_removed_freeze_key_is_an_unknown_top_level_key() -> None:
    printed = _printed_defects('frozen_until = { trigger = "T", ruled_on = 2026-11-01 }')

    assert printed == ["body malformed: frozen_until: unknown top-level key frozen_until"]


@pytest.mark.parametrize(
    "wait_line",
    [
        pytest.param('wait = { operator = "Say \\"yes\\".", since = 2026-11-01 }', id="operator"),
        pytest.param("wait = { until = 2026-12-01, since = 2026-11-01 }", id="until"),
        pytest.param('wait = { trigger = "A fact.", since = 2026-11-01 }', id="trigger"),
    ],
)
def test_a_wait_survives_a_rewrite_of_the_block(wait_line: str) -> None:
    original = block_body(MINIMAL_BLOCK_TOML + wait_line + "\n")
    located = body.locate_block(original)

    rewritten = body.replace_block(original, located, located.data)

    assert body.parse_body(rewritten).wait == body.parse_body(original).wait
    assert wait_line in rewritten


@pytest.mark.parametrize(
    ("wait", "today", "over"),
    [
        pytest.param(item_wait.UntilWait(DEADLINE, SINCE), date(2026, 11, 30), False, id="before"),
        pytest.param(item_wait.UntilWait(DEADLINE, SINCE), DEADLINE, True, id="on-the-day"),
        pytest.param(item_wait.UntilWait(DEADLINE, SINCE), date(2027, 1, 1), True, id="after"),
        pytest.param(
            item_wait.OperatorWait("Step.", SINCE), date(2099, 1, 1), False, id="operator"
        ),
        pytest.param(item_wait.TriggerWait("Fact.", SINCE), date(2099, 1, 1), False, id="trigger"),
    ],
)
def test_only_a_date_wait_ends_by_itself(wait: item_wait.ItemWait, today: date, over: bool) -> None:
    assert item_wait.is_over(wait, today) is over


@pytest.mark.parametrize(
    ("block", "step", "today", "since"),
    [
        pytest.param({}, "Step.", date(2026, 11, 9), date(2026, 11, 9), id="none-yet"),
        pytest.param(
            {"wait": {"operator": "Step.", "since": SINCE}},
            "Step.",
            date(2026, 11, 9),
            SINCE,
            id="same-step-keeps-since",
        ),
        pytest.param(
            {"wait": {"operator": "Other.", "since": SINCE}},
            "Step.",
            date(2026, 11, 9),
            date(2026, 11, 9),
            id="other-step",
        ),
        pytest.param(
            {"wait": {"until": DEADLINE, "since": SINCE}},
            "Step.",
            date(2026, 11, 9),
            date(2026, 11, 9),
            id="other-kind",
        ),
        pytest.param(
            {"wait": "broken"},
            "Step.",
            date(2026, 11, 9),
            date(2026, 11, 9),
            id="malformed-wait",
        ),
    ],
)
def test_a_step_wait_carries_the_step_and_the_day_it_began(
    block: dict[str, object], step: str, today: date, since: date
) -> None:
    table = item_wait.operator_wait_table(step, today, block)

    assert table == {"operator": step, "since": since}
