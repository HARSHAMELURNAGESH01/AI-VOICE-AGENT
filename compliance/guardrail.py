"""
compliance/guardrail.py

The deterministic last line of defense. Every reply the LLM produces passes
through check_outgoing() BEFORE it is spoken/sent. If the reply violates a
rule, it is blocked and replaced with a safe fallback -- and the violation is
logged. The LLM can be manipulated; this filter cannot.

Design principle: laws are enforced by code, not by trusting the model.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config"


def _load(name: str) -> dict:
    with open(CONFIG_PATH / name) as f:
        return json.load(f)


@dataclass
class GuardrailResult:
    allowed: bool
    violations: list = field(default_factory=list)
    safe_text: str = ""  # what should actually be spoken


class Guardrail:
    def __init__(self):
        rules = _load("compliance_rules.json")
        listings = _load("property_listings.json")
        concessions = _load("concessions.json")

        self.blocked_phrases = [
            p.lower() for p in rules["steering_proxy_phrases"]["blocked_in_output"]
        ]
        self.forbidden_promises = [p.lower() for p in rules["forbidden_promises"]]

        # Approved dollar amounts: listed rents, fees, concession values.
        # Any OTHER dollar amount in agent output is treated as an
        # unapproved/hallucinated offer and blocked.
        self.approved_amounts: set[int] = set()
        for u in listings["units"]:
            self.approved_amounts.add(int(u["rent"]))
        self.approved_amounts.add(int(listings["property"]["application_fee"]))
        self.approved_amounts.add(300)  # pet deposit (from pet_policy text)
        self.approved_amounts.add(50)   # second parking spot monthly
        for c in concessions["concessions"]:
            self.approved_amounts.add(int(c["value_usd"]))

        self.fallback = (
            "I want to make sure I give you accurate information on that, so let "
            "me have our leasing manager follow up with you directly. Is there "
            "anything else about the unit or booking a viewing I can help with?"
        )

    def _extract_dollar_amounts(self, text: str) -> list[int]:
        amounts = []
        for m in re.finditer(r"\$\s?([\d,]+(?:\.\d{1,2})?)", text):
            try:
                amounts.append(int(float(m.group(1).replace(",", ""))))
            except ValueError:
                continue
        return amounts

    def check_outgoing(self, text: str) -> GuardrailResult:
        """Validate agent output before it is spoken. Returns the text to use."""
        violations = []
        lowered = text.lower()

        for phrase in self.blocked_phrases:
            if phrase in lowered:
                violations.append(
                    {"type": "fair_housing_steering", "matched": phrase}
                )

        for phrase in self.forbidden_promises:
            if phrase in lowered:
                violations.append(
                    {"type": "forbidden_promise", "matched": phrase}
                )

        for amount in self._extract_dollar_amounts(text):
            if amount not in self.approved_amounts:
                violations.append(
                    {"type": "unapproved_dollar_amount", "matched": f"${amount}"}
                )

        if violations:
            return GuardrailResult(allowed=False, violations=violations,
                                   safe_text=self.fallback)
        return GuardrailResult(allowed=True, violations=[], safe_text=text)

    def check_disclosure(self, first_agent_message: str) -> bool:
        """The first message of every conversation must disclose AI status."""
        lowered = first_agent_message.lower()
        return ("ai" in lowered and "assistant" in lowered) or "virtual assistant" in lowered
