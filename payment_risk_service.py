"""HTTP entry point for the payment-risk workflow."""

from fastapi import FastAPI, HTTPException
from openai import APIConnectionError, APIStatusError, RateLimitError

from fintech_cost_guard import InfraiRiskModel, PaymentEvent, RiskAssessment, assess_payment


service = FastAPI(title="Payment cost guard")


@service.post("/assess-payment", response_model=RiskAssessment)
def assess_payment_request(event: PaymentEvent) -> RiskAssessment:
    try:
        return assess_payment(event, InfraiRiskModel())
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail="model capacity reached; retry later") from exc
    except APIStatusError as exc:
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        raise HTTPException(status_code=status, detail="model request rejected") from exc
    except APIConnectionError as exc:
        raise HTTPException(status_code=503, detail="model transport unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
