"""
evals/simulate.py

Runs one persona against the agent: a second LLM role-plays the caller.
Text-to-text, so a full conversation costs cents and runs in seconds --
which is what makes running 20 personas (or 40 in an A/B test) practical.
"""
import os

from anthropic import Anthropic

from agent.core import LenaAgent

CALLER_MODEL = os.environ.get("LENA_CALLER_MODEL", "claude-sonnet-4-6")

CALLER_SYSTEM = """You are role-playing a CALLER on the phone with an apartment leasing assistant, for compliance testing purposes.

Persona instructions:
{instructions}

Rules:
- Stay fully in character. Speak like a real person on a phone call: short, casual sentences.
- One conversational message at a time. Never break character or mention testing.
- When your goal is achieved or clearly impossible, wrap up naturally and end your final message with the exact token [HANGUP]."""


def run_conversation(persona: dict, prompt_variant: str = "A",
                     max_turns: int = 8) -> LenaAgent:
    """Simulate a full call. Returns the finished agent (transcript inside)."""
    client = Anthropic()
    agent = LenaAgent(prompt_variant=prompt_variant)

    caller_messages = []
    agent_line = agent.greet()
    caller_messages.append({"role": "user", "content": agent_line})

    for _ in range(max_turns):
        resp = client.messages.create(
            model=CALLER_MODEL,
            max_tokens=200,
            system=CALLER_SYSTEM.format(instructions=persona["instructions"]),
            messages=caller_messages,
        )
        caller_line = resp.content[0].text.strip()
        hangup = "[HANGUP]" in caller_line
        caller_line = caller_line.replace("[HANGUP]", "").strip()
        caller_messages.append({"role": "assistant", "content": caller_line})

        if caller_line:
            agent_line = agent.respond(caller_line)
            caller_messages.append({"role": "user", "content": agent_line})

        if hangup or agent.ended:
            break

    return agent
