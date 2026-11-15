"""The block's one typed `handover` (`specs/body-block.spec.md`): reading, refusing, writing."""

from datetime import date

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body, complete_contract

from aco import body, item_handover, protocol

TAKEN_ON = date(2026, 11, 15)
RECORD = item_handover.ItemHandover("Ada", "Grace", "The operator restarted every head.", TAKEN_ON)
RECORD_LINE = (
    'handover = { from = "Ada", to = "Grace", '
    'reason = "The operator restarted every head.", on = 2026-11-15 }'
)


def test_a_block_reads_its_one_handover() -> None:
    located = body.locate_block(block_body(MINIMAL_BLOCK_TOML + RECORD_LINE + "\n"))

    assert item_handover.parse_handover(located.data) == RECORD


def test_a_block_without_a_handover_reads_none() -> None:
    located = body.locate_block(block_body(MINIMAL_BLOCK_TOML))

    assert item_handover.parse_handover(located.data) is None


@pytest.mark.parametrize(
    ("handover_line", "printed"),
    [
        pytest.param(
            'handover = "Grace"',
            "body malformed: handover: handover must be a table",
            id="not-a-table",
        ),
        pytest.param(
            'handover = { to = "Grace", reason = "R", on = 2026-11-15 }',
            "body malformed: handover.from: handover.from must be a non-empty one-line string",
            id="missing-from",
        ),
        pytest.param(
            'handover = { from = "Ada", to = " ", reason = "R", on = 2026-11-15 }',
            "body malformed: handover.to: handover.to must be a non-empty one-line string",
            id="blank-to",
        ),
        pytest.param(
            'handover = { from = "Ada", to = "Grace", reason = "a\\nb", on = 2026-11-15 }',
            "body malformed: handover.reason: handover.reason must be a non-empty one-line string",
            id="reason-over-two-lines",
        ),
        pytest.param(
            'handover = { from = "Ada", to = "Grace", reason = "R", on = "today" }',
            "body malformed: handover.on: handover.on must be a TOML local date",
            id="on-not-a-date",
        ),
        pytest.param(
            'handover = { from = "Ada", to = "Grace", reason = "R", on = 2026-11-15, by = 1 }',
            "body malformed: handover.by: unknown key handover.by",
            id="unknown-key",
        ),
    ],
)
def test_a_block_refuses_a_malformed_handover(handover_line: str, printed: str) -> None:
    parsed = body.parse_body(block_body(MINIMAL_BLOCK_TOML + handover_line + "\n"))

    assert parsed.read_state is body.BodyReadState.MALFORMED
    assert [body.body_defect_text(defect) for defect in parsed.contract.defects] == [printed]


def test_a_block_with_a_handover_renders_it_back_unchanged() -> None:
    text = block_body(MINIMAL_BLOCK_TOML + "\n" + RECORD_LINE)
    located = body.locate_block(text)

    assert body.replace_block(text, located, located.data) == text


def test_a_written_handover_is_a_valid_block() -> None:
    table = item_handover.handover_table(RECORD)

    written = complete_contract("Build it.", handover=table)

    assert body.parse_body(written).read_state is body.BodyReadState.VALID
    assert item_handover.parse_handover(body.locate_block(written).data) == RECORD


@pytest.mark.parametrize(
    ("identity", "label", "route"),
    [
        pytest.param(
            protocol.IssueIdentity(72),
            lambda number: f"#{number}",
            "aco handover 72 --from 'Claude af54' --reason <text>",
            id="a-github-item-claim-names-its-number",
        ),
        pytest.param(
            protocol.IssueIdentity(72),
            lambda _number: "aco-abc123",
            "aco handover aco-abc123 --from 'Claude af54' --reason <text>",
            id="a-state-ref-item-claim-names-its-id",
        ),
        pytest.param(protocol.LaneIdentity(), str, None, id="a-lane-claim-has-none"),
    ],
)
def test_the_route_names_the_handover_command_of_an_item_claim(
    identity: protocol.ClaimIdentity, label: protocol.ItemLabel, route: str | None
) -> None:
    assert item_handover.handover_route(identity, "Claude af54", label) == route
