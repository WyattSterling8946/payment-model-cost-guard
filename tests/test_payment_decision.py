from decimal import Decimal

from fintech_cost_guard import ModelEvidence, PaymentEvent, assess_payment


class HighRiskModel:
    def assess(self, event: PaymentEvent) -> ModelEvidence:
        return ModelEvidence(
            risk_label="high",
            reason="country mismatch on a high-value payment",
            cost_usd=Decimal("0.0041"),
            served_by="test-vendor",
        )


def test_high_risk_payment_is_held_with_auditable_cost() -> None:
    event = PaymentEvent(
        payment_id="pay_1042",
        amount_minor=250000,
        currency="USD",
        merchant_country="US",
        card_country="GB",
    )

    result = assess_payment(event, HighRiskModel())

    assert result.action == "manual_review"
    assert result.model_cost_usd == Decimal("0.0041")
    assert result.notification == (
        "payment=pay_1042 action=manual_review risk=high "
        "model_cost_usd=0.0041 served_by=test-vendor"
    )
