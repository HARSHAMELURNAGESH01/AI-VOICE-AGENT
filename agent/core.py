"""
agent/core.py

Lena's conversation engine. Text-first by design: the same engine powers
terminal chat (demo.py), automated evals (evals/), and the phone adapter
(telephony/). One brain, many mouths.

Per turn:
  1. Caller message scanned by compliance/triggers.py; any trigger injects an
     explicit compliance instruction into context (and is logged).
  2. Claude responds, using tools in a loop as needed.
  3. Final text passes through the guardrail. Violations are blocked, replaced
     with a safe fallback, and logged. The caller never hears the violation.
  4. Token usage accumulates into a per-conversation cost record.
"""
import os
import uuid

from anthropic import Anthropic

from compliance.guardrail import Guardrail
from compliance.triggers import detect, TRIGGER_GUIDANCE
from db.database import Database
from prompts.system import get_system_prompt
from tools.leasing import LeasingTools, TOOL_SCHEMAS

MODEL = os.environ.get("LENA_MODEL", "claude-sonnet-4-6")

# USD per million tokens; override via env if pricing changes.
PRICE_IN = float(os.environ.get("LENA_PRICE_IN", "3.0"))
PRICE_OUT = float(os.environ.get("LENA_PRICE_OUT", "15.0"))


class LenaAgent:
    def __init__(self, db: Database | None = None, prompt_variant: str = "A"):
        self.client = Anthropic()
        self.db = db or Database()
        self.tools = LeasingTools(self.db)
        self.guardrail = Guardrail()
        self.system_prompt = get_system_prompt(prompt_variant)
        self.prompt_variant = prompt_variant

        self.conversation_id = str(uuid.uuid4())[:8]
        self.messages: list[dict] = []
        self.transcript: list[dict] = []
        self.triggers_log: list[dict] = []
        self.guardrail_events: list[dict] = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.ended = False

    # ------------------------------------------------------------------
    def greet(self) -> str:
        """Produce the opening message (with mandatory AI disclosure)."""
        return self._run_llm_turn(
            "(The call just connected. Greet the caller and disclose that you "
            "are an AI leasing assistant.)"
        )

    def respond(self, caller_text: str) -> str:
        """Process one caller message and return Lena's (guarded) reply."""
        triggers = detect(caller_text)
        content = caller_text
        if triggers:
            self.triggers_log.extend(
                {**t, "caller_text": caller_text} for t in triggers
            )
            guidance = "\n".join(
                TRIGGER_GUIDANCE[t["type"]] for t in triggers if t["type"] in TRIGGER_GUIDANCE
            )
            content = f"{caller_text}\n\n[{guidance}]"

        self.transcript.append({"role": "caller", "content": caller_text,
                                "triggers": [t["type"] for t in triggers]})
        return self._run_llm_turn(content)

    # ------------------------------------------------------------------
    def _run_llm_turn(self, user_content: str) -> str:
        self.messages.append({"role": "user", "content": user_content})

        # Tool-use loop
        while True:
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=400,
                system=self.system_prompt,
                tools=TOOL_SCHEMAS,
                messages=self.messages,
            )
            self.input_tokens += resp.usage.input_tokens
            self.output_tokens += resp.usage.output_tokens

            if resp.stop_reason != "tool_use":
                break

            self.messages.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    output = self.tools.execute(block.name, dict(block.input))
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                    })
                    self.transcript.append({"role": "tool", "tool": block.name,
                                            "input": dict(block.input),
                                            "output": output})
            self.messages.append({"role": "user", "content": results})

        raw_text = "".join(b.text for b in resp.content if b.type == "text").strip()

        if "[END_CALL]" in raw_text:
            self.ended = True
            raw_text = raw_text.replace("[END_CALL]", "").strip()

        # ------------------------- guardrail: last line of defense
        result = self.guardrail.check_outgoing(raw_text)
        final_text = result.safe_text
        if not result.allowed:
            self.guardrail_events.append({
                "blocked_text": raw_text,
                "violations": result.violations,
            })

        self.messages.append({"role": "assistant", "content": final_text})
        self.transcript.append({"role": "agent", "content": final_text,
                                "guardrail_blocked": not result.allowed})
        return final_text

    # ------------------------------------------------------------------
    def cost(self) -> dict:
        llm_cost = (self.input_tokens * PRICE_IN + self.output_tokens * PRICE_OUT) / 1_000_000
        return {
            "llm_input_tokens": self.input_tokens,
            "llm_output_tokens": self.output_tokens,
            "llm_cost_usd": round(llm_cost, 6),
            "model": MODEL,
            "note": "STT/TTS costs added by the telephony layer when voice is used.",
        }

    def finalize(self, qa_scorecard: dict | None = None,
                 summary: dict | None = None) -> str:
        """Persist the conversation to the tamper-evident audit log."""
        return self.db.save_conversation(
            conversation_id=self.conversation_id,
            transcript=self.transcript,
            triggers=self.triggers_log,
            guardrail_events=self.guardrail_events,
            qa_scorecard=qa_scorecard,
            cost=self.cost(),
            summary=summary,
        )
