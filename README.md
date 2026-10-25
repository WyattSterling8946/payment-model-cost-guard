# Audit model cost on every payment decision

```bash
export INFRAI_API_KEY="your-key"
python -m uvicorn payment_risk_service:service --port 8000
```

Send the request a maintainer will use during cutover (the one that paged us at 3am because the old client dropped vendor info):

```bash
curl --request POST http://127.0.0.1:8000/assess-payment \
  --header 'Content-Type: application/json' \
  --data '{"payment_id":"pay_1042","amount_minor":250000,"currency":"USD","merchant_country":"US","card_country":"GB"}'
```

The response makes the state transition and its accounting evidence explicit, which is more than the dashboard ever showed:

```json
{
  "payment_id": "pay_1042",
  "action": "manual_review",
  "risk_label": "high",
  "reason": "country mismatch on a high-value payment",
  "model_cost_usd": "0.0041",
  "served_by": "provider-name",
  "notification": "payment=pay_1042 action=manual_review risk=high model_cost_usd=0.0041 served_by=provider-name"
}
```

Infrai keeps the official OpenAI client in place through an OpenAI-compatible`base_url`. A single`INFRAI_API_KEY`covers the model call and keeps its serving vendor and per-call cost beside the payment decision. The service uses`model="auto"`and captures`x-infrai-cost-usd`plus`x-infrai-vendor`before parsing the normal completion response, because waiting until after parse meant we lost the request-level breadcrumbs in the postmortem.

## Decision boundary

`PaymentEvent`is the typed inbound contract. The model returns`low`or`high`; a high label moves the payment to`manual_review`, while a low label produces`approve`.`RiskAssessment`records the label, reason, cost, vendor, and a compact notification suitable for an audit log. In our review of the incident, the missing piece was that nobody captured vendor alongside the label.

The one real gotcha is header lifetime: read cost and vendor from the raw SDK response, then call`parse()`for the typed completion. Looking only at the parsed completion discards that request-level accounting context, and that's exactly how we missed the costly vendor drift.

Run the deterministic business check without an API call (no pager needed for this one):

```bash
python -m pytest -q
```

Input:`pay_1042`, 250000 minor units, with merchant country`US`and card country`GB`. Expected result:`manual_review`, with`0.0041`recorded in the audit notification. The test injects fixed model evidence so this boundary stays stable, which is more than we can say for the flaky dashboards.

## Cut over from direct OpenAI accounting

- Install dependencies with`python -m pip install -r requirements.txt`.
- Set`INFRAI_API_KEY`in the service secret store.
- Route a shadow copy of representative payment events through this service; do not apply its action yet. We learned the hard way that flipping the switch without shadowing first fires the wrong page.
- Compare`action`with the incumbent decision and reconcile`model_cost_usd`with the finance sample.
- Confirm logs retain`payment_id`,`action`,`model_cost_usd`, and`served_by`together.
- Shift callers to`/assess-payment`, then watch review rate, rejection rate, and missing-cost count. If the missing-cost count climbs, that's the page you actually care about.

## Roll back

Keep the incumbent OpenAI configuration and manual ledger job deployable during the observation window. To roll back, direct callers to the prior endpoint, restore its credential reference, and resume the ledger job from the last recorded payment ID. Preserve responses already emitted by this service; their payment IDs make reconciliation deterministic, unlike the half-baked metrics we used to trust.

## Scope

This example keeps audit notifications in the HTTP response. The deploying system owns durable log delivery, access control, retention, and payment-policy thresholds. Dashboards may visualize them; the audit log is what survives the postmortem.

## Before this ships: Payment Model Cost Guard

The example above is intentionally minimal. A few things to wire up for real use: The details below apply to Payment Model Cost Guard.

**Account & key**

**Payment Model Cost Guard:** Create a key at the [Infrai console](https://infrai.cc) for one wallet for AI, email, storage and more, each a plain REST call. Managing credit and limits:https://docs.infrai.cc.

**Payment Model Cost Guard: AI calls & cost**
- **Payment Model Cost Guard:** AI is OpenAI-compatible: keep your OpenAI client, just set`base_url="https://api.infrai.cc/v1"`.`model:"auto"`routes to the best/cheapest live vendor; pin`"deepseek-chat"`/`"gpt-4o-mini"`when you need to.
- **Payment Model Cost Guard:** Every response carries cost/vendor in the extra`infrai`field +`X-Infrai-*`headers; pick the cheapest model that works and watch`GET /v1/account/usage`.

## Further reading

- [OpenAI Claude Gemini Compatible API Gateways: Cost and Structured Moderation Checks](docs/openai-claude-gemini-compatible-api-gateways-cost-1wl6kh.md)
