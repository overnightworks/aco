"""`aco rule --via default` through the real CLI: it keeps the recommended
option only while that option can be taken back and the line is not a money,
access or data-risk decision (RULE-45)."""

import pytest
from option_cards import (
    assert_refusal_writes_nothing,
    card,
    card_head,
    card_option_a,
    card_option_b,
    decide,
    item_body,
    serve_item,
    shown_hash,
)


@pytest.mark.usefixtures("github_world")
class TestRuleDefaultStandsInOnlyForAReversibleChoice:
    @pytest.mark.parametrize(
        ("card_text", "reason"),
        [
            pytest.param(
                card(
                    None, card_option_a(('undo = "reversible"', 'undo = "final"')), card_option_b()
                ),
                "its recommended option A is final",
                id="final",
            ),
            *(
                pytest.param(
                    card(card_head(('decision_kind = "product"', f'decision_kind = "{kind}"'))),
                    f"its decision kind is {kind}",
                    id=kind,
                )
                for kind in ("money", "access", "data_risk")
            ),
        ],
    )
    def test_a_default_ruling_refuses_and_writes_nothing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        card_text: str,
        reason: str,
    ) -> None:
        """Spec: RULE-45 -- one sentence naming the line and the reason."""
        client = serve_item(monkeypatch, item_body(card_text))
        message = f"line 2 cannot be ruled --via default: {reason}; the operator rules it"
        assert_refusal_writes_nothing(
            client,
            capsys,
            decide("A", "default", shown_hash(item_body(card_text), 2)),
            message,
            "invalid_usage",
        )
