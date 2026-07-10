"""
tools/leasing.py

The agent's tools. The LLM calls these; they operate on config + database.
Key design: get_concession_offer is the ONLY path to a discount -- the model
cannot invent one, and the guardrail independently blocks unapproved dollar
amounts in output. Two layers, one policy.
"""
import json
from pathlib import Path

from db.database import Database

CONFIG_PATH = Path(__file__).parent.parent / "config"

with open(CONFIG_PATH / "property_listings.json") as f:
    LISTINGS = json.load(f)
with open(CONFIG_PATH / "concessions.json") as f:
    CONCESSIONS = json.load(f)


# Tool schemas passed to the Claude API
TOOL_SCHEMAS = [
    {
        "name": "check_availability",
        "description": "List currently available units, optionally filtered by number of bedrooms.",
        "input_schema": {
            "type": "object",
            "properties": {
                "bedrooms": {"type": "integer", "description": "Filter by bedroom count (optional)"}
            },
        },
    },
    {
        "name": "get_viewing_slots",
        "description": "Get available viewing appointment slots.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "book_viewing",
        "description": "Book a viewing appointment. Confirm unit, slot, name, and phone with the caller first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "unit_id": {"type": "string"},
                "slot": {"type": "string"},
                "caller_name": {"type": "string"},
                "caller_phone": {"type": "string"},
            },
            "required": ["unit_id", "slot", "caller_name", "caller_phone"],
        },
    },
    {
        "name": "get_concession_offer",
        "description": "Check whether an approved concession applies to this caller's situation. This is the ONLY way to offer any discount or incentive. Describe the caller's situation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "situation": {
                    "type": "string",
                    "description": "e.g. 'comparing with another property', 'booking within 7 days', 'has two cars', 'asking for lower rent'",
                }
            },
            "required": ["situation"],
        },
    },
    {
        "name": "escalate_to_human",
        "description": "Flag this conversation for the human leasing manager. Use for legal mentions, distress, rent negotiation requests, or anything outside your knowledge.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "log_opt_out",
        "description": "Record that this caller does not want to be contacted again.",
        "input_schema": {
            "type": "object",
            "properties": {"caller_phone": {"type": "string"}},
            "required": ["caller_phone"],
        },
    },
]


class LeasingTools:
    """Executes tool calls. Records escalations/opt-outs for QA visibility."""

    def __init__(self, db: Database):
        self.db = db
        self.escalations: list[dict] = []
        self.bookings: list[dict] = []
        self.opt_outs: list[str] = []

    def execute(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return json.dumps({"error": f"unknown tool {name}"})
        return handler(**args)

    def _tool_check_availability(self, bedrooms: int | None = None) -> str:
        units = [u for u in LISTINGS["units"] if u["available"]]
        if bedrooms is not None:
            units = [u for u in units if u["bedrooms"] == bedrooms]
        return json.dumps({"available_units": units})

    def _tool_get_viewing_slots(self) -> str:
        return json.dumps({"slots": LISTINGS["property"]["viewing_slots"]})

    def _tool_book_viewing(self, unit_id: str, slot: str,
                           caller_name: str, caller_phone: str) -> str:
        valid_units = {u["unit_id"] for u in LISTINGS["units"] if u["available"]}
        if unit_id not in valid_units:
            return json.dumps({"error": f"unit {unit_id} is not available"})
        if slot not in LISTINGS["property"]["viewing_slots"]:
            return json.dumps({"error": f"slot '{slot}' is not offered",
                               "valid_slots": LISTINGS["property"]["viewing_slots"]})
        self.db.get_or_create_caller(caller_phone, caller_name)
        booking_id = self.db.book_viewing(caller_phone, caller_name, unit_id, slot)
        booking = {"booking_id": booking_id, "unit_id": unit_id, "slot": slot,
                   "caller_name": caller_name}
        self.bookings.append(booking)
        return json.dumps({"confirmed": True, **booking})

    def _tool_get_concession_offer(self, situation: str) -> str:
        s = situation.lower()
        if any(k in s for k in ["lower rent", "reduce rent", "cheaper rent", "negotiate rent", "rent down"]):
            self.escalations.append({"reason": "rent negotiation request"})
            return json.dumps({
                "offer_available": False,
                "instruction": CONCESSIONS["hard_limits"]["rent_negotiation"],
            })
        matches = []
        if any(k in s for k in ["7 days", "this week", "book", "viewing soon", "tour"]):
            matches.append(CONCESSIONS["concessions"][0])
        if any(k in s for k in ["comparing", "another property", "other place", "price", "hesitat", "expensive"]):
            matches.append(CONCESSIONS["concessions"][1])
        if any(k in s for k in ["two cars", "two vehicles", "second car", "2 cars"]):
            matches.append(CONCESSIONS["concessions"][2])
        if not matches:
            return json.dumps({"offer_available": False,
                               "instruction": "No approved concession applies. Do not invent one."})
        return json.dumps({"offer_available": True, "approved_offers": matches})

    def _tool_escalate_to_human(self, reason: str) -> str:
        self.escalations.append({"reason": reason})
        return json.dumps({"escalated": True,
                           "note": "The leasing manager will follow up. Tell the caller this."})

    def _tool_log_opt_out(self, caller_phone: str) -> str:
        self.db.log_opt_out(caller_phone)
        self.opt_outs.append(caller_phone)
        return json.dumps({"opted_out": True,
                           "note": "Confirm to the caller their number is removed, then end the call."})
