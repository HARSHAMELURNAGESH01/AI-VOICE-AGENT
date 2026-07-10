"""
notifications/sms.py

Post-call SMS follow-up. When a call ends with a booked viewing, the caller
gets a confirmation text -- the same multi-channel pattern production
platforms use (voice + SMS with shared context).

Modes (SMS_MODE in .env):
  log     (default) -- compose + store the message, don't hit the network.
                       Dashboard shows it as "composed (log mode)".
  twilio            -- actually send via Twilio Messages API. Requires a
                       number with US A2P 10DLC registration completed.

Every message (sent or logged) is stored in the sms_log table for the
dashboard and auditability.
"""
import json
import os
from pathlib import Path

from db.database import Database

CONFIG_PATH = Path(__file__).parent.parent / "config"

with open(CONFIG_PATH / "property_listings.json") as f:
    _PROPERTY = json.load(f)["property"]


def _compose_booking_confirmation(caller_name: str, unit_id: str, slot: str) -> str:
    first_name = (caller_name or "there").split()[0]
    return (
        f"Hi {first_name}! This is Lena, the AI leasing assistant for "
        f"{_PROPERTY['name']}. Your viewing of unit {unit_id} is confirmed "
        f"for {slot}. Address: {_PROPERTY['address']}. "
        f"Reply STOP to opt out of messages."
    )


def send_booking_confirmations(agent, db: Database | None = None) -> list[dict]:
    """Send/log a confirmation SMS for each booking made during the call."""
    db = db or agent.db
    mode = os.environ.get("SMS_MODE", "log").lower()
    results = []

    for b in agent.tools.bookings:
        phone = _find_booking_phone(agent, b)
        body = _compose_booking_confirmation(b.get("caller_name"), b["unit_id"], b["slot"])
        status = "logged"

        if mode == "twilio" and phone and phone.startswith("+"):
            try:
                from twilio.rest import Client
                client = Client(os.environ["TWILIO_ACCOUNT_SID"],
                                os.environ["TWILIO_AUTH_TOKEN"])
                client.messages.create(
                    to=phone, from_=os.environ["TWILIO_FROM_NUMBER"], body=body
                )
                status = "sent"
            except Exception as e:  # never let SMS failure break call teardown
                status = f"failed: {e.__class__.__name__}"

        record = {"conversation_id": agent.conversation_id, "to": phone or "unknown",
                  "body": body, "status": status, "mode": mode}
        db.log_sms(**record)
        results.append(record)
    return results


def _find_booking_phone(agent, booking: dict) -> str | None:
    """Booking rows store the phone via the tool call; recover it from the
    transcript's tool entries (phone was confirmed verbally on the call)."""
    for t in agent.transcript:
        if t.get("role") == "tool" and t.get("tool") == "book_viewing":
            if t["input"].get("unit_id") == booking["unit_id"]:
                return t["input"].get("caller_phone")
    return None
