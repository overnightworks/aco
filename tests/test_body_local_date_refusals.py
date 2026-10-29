"""Spec: BODY-23, BODY-32 -- a `ruled_on` that is not a TOML local date is refused
with the sentence the spec prints."""

from __future__ import annotations

import pytest
from board_fixtures import MINIMAL_BLOCK_TOML, block_body

from aco import body


@pytest.mark.parametrize(
    "block_tail, printed",
    [
        pytest.param(
            '[[expectation]]\ntext = "T"\nruling = "yes"\nruled_on = "2026-10-01"\n',
            "body malformed: expectation[0].ruled_on: "
            "expectation[0].ruled_on must be a TOML local date",
            id="BODY-32",
        ),
        pytest.param(
            'frozen_until = { trigger = "T", ruled_on = "2026-10-01" }\n',
            "body malformed: frozen_until.ruled_on: "
            "frozen_until.ruled_on must be a TOML local date",
            id="BODY-23",
        ),
    ],
)
def test_a_string_ruled_on_is_refused_as_not_a_local_date(block_tail: str, printed: str) -> None:
    parsed = body.parse_body(block_body(MINIMAL_BLOCK_TOML + block_tail))
    assert parsed.read_state is body.BodyReadState.MALFORMED
    assert [body.body_defect_text(defect) for defect in parsed.contract.defects] == [printed]
