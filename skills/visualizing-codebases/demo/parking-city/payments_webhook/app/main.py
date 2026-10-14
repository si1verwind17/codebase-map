"""Inbound webhook from Stripe: records payment results."""
import logging

import stripe
from fastapi import FastAPI, Header, HTTPException, Request

from common_py.config import env

from . import store

log = logging.getLogger("payments-webhook")
app = FastAPI(title="payments-webhook")


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(...)) -> dict:
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, env("STRIPE_WEBHOOK_SECRET"))
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="bad signature")

    kind = event["type"]
    intent = event["data"]["object"]
    if kind in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        status = "SUCCEEDED" if kind.endswith("succeeded") else "FAILED"
        reservation_id = intent.get("metadata", {}).get("reservation_id")
        store.record_payment(event["id"], intent["id"], reservation_id, status, intent["amount"])
        if reservation_id:
            # Shortcut taken to make the booking page update instantly: this
            # service writes a table that the reservations service owns.
            store.mark_reservation(reservation_id, "PAID" if status == "SUCCEEDED" else "FAILED")
    else:
        log.info("ignoring stripe event %s", kind)
    return {"received": True}
