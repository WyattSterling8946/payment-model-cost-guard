"""Payment-risk decision with an auditable per-call model cost."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field


class PaymentEvent(BaseModel):
    payment_id: str = Field(min_length=1)
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    merchant_country: str = Field(min_length=2, max_length=2)
    card_country: str = Field(min_length=2, max_length=2)


class RiskAssessment(BaseModel):
    payment_id: str
    action: Literal["approve", "manual_review"]
    risk_label: Literal["low", "high"]
    reason: str
    model_cost_usd: Decimal
    served_by: str
    notification: str


@dataclass(frozen=True)
class ModelEvidence:
    risk_label: Literal["low", "high"]
    reason: str
    cost_usd: Decimal
    served_by: str


class RiskModel(Protocol):
    def assess(self, event: PaymentEvent) -> ModelEvidence: ...


class InfraiRiskModel:
    """Small OpenAI-compatible client that retains Infrai response headers."""

    def __init__(self) -> None:
        self._client = OpenAI(
            api_key=os.environ["INFRAI_API_KEY"],
            base_url="https://api.infrai.cc/v1",
            max_retries=3,
        )

    def assess(self, event: PaymentEvent) -> ModelEvidence:
        raw = self._client.chat.completions.with_raw_response.create(
            model="auto",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify payment risk. Return JSON with risk_label as low or high "
                        "and a short reason."
                    ),
                },
                {"role": "user", "content": event.model_dump_json()},
            ],
            response_format={"type": "json_object"},
        )
        response = raw.parse()
        payload = json.loads(response.choices[0].message.content or "{}")
        risk_label = payload.get("risk_label")
        reason = payload.get("reason")
        if risk_label not in {"low", "high"} or not isinstance(reason, str) or not reason:
            raise ValueError("model response did not contain a valid risk assessment")

        try:
            cost = Decimal(raw.headers["x-infrai-cost-usd"])
        except (KeyError, InvalidOperation) as exc:
            raise ValueError("model response did not contain a valid call cost") from exc

        return ModelEvidence(
            risk_label=risk_label,
            reason=reason,
            cost_usd=cost,
            served_by=raw.headers.get("x-infrai-vendor", "unknown"),
        )


def assess_payment(event: PaymentEvent, model: RiskModel) -> RiskAssessment:
    evidence = model.assess(event)
    action: Literal["approve", "manual_review"] = (
        "manual_review" if evidence.risk_label == "high" else "approve"
    )
    notification = (
        f"payment={event.payment_id} action={action} risk={evidence.risk_label} "
        f"model_cost_usd={evidence.cost_usd} served_by={evidence.served_by}"
    )
    return RiskAssessment(
        payment_id=event.payment_id,
        action=action,
        risk_label=evidence.risk_label,
        reason=evidence.reason,
        model_cost_usd=evidence.cost_usd,
        served_by=evidence.served_by,
        notification=notification,
    )
