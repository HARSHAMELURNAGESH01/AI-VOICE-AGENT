"""
supervisor/summary.py

Generates the LEASING TEAM HANDOFF SUMMARY after each call -- the thing a
human salesperson actually reads. Distinct from the QA scorecard (which is
about compliance); this is about the lead: who called, what they want,
what happened, and what the human should do next.
"""
import json
import os

from anthropic import Anthropic

MODEL = os.environ.get("LENA_QA_MODEL", "claude-sonnet-4-6")

SUMMARY_PROMPT = """You are writing a call summary for an apartment leasing team.
You will receive a JSON transcript of a call handled by Lena, the AI leasing assistant
(roles: caller, agent, tool).

Respond with ONLY valid JSON, no markdown fences:

{
  "one_line": "single sentence a busy salesperson reads first",
  "caller_name": "name if given, else null",
  "caller_phone": "phone if given, else null",
  "outcome": "viewing_booked | interested_no_booking | not_interested | opt_out | escalated | wrong_number | incomplete",
  "interested_units": ["unit ids discussed with interest, e.g. B-204"],
  "booking": "e.g. 'B-204, Tuesday 10:00 AM' or null",
  "key_questions": ["questions the caller asked"],
  "objections_or_concerns": ["price concerns, comparisons, hesitations"],
  "follow_up_actions": ["concrete next steps for the human, e.g. 'Call back about rent negotiation request'"],
  "sentiment": "positive | neutral | negative",
  "priority": "hot | warm | cold"
}

Priority guide: hot = booked or clearly ready to book; warm = interested but undecided;
cold = not interested, opt-out, or wrong number."""


class LeasingSummary:
    def __init__(self):
        self.client = Anthropic()

    def generate(self, transcript: list) -> dict:
        resp = self.client.messages.create(
            model=MODEL,
            max_tokens=600,
            system=SUMMARY_PROMPT,
            messages=[{"role": "user", "content": json.dumps(transcript)}],
        )
        raw = resp.content[0].text.strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"one_line": "Summary generation failed", "error": raw[:200]}
