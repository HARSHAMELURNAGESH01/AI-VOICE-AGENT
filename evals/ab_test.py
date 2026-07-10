"""
evals/ab_test.py

Prompt A/B testing: run the SAME persona suite against two prompt variants
and compare. Answers the question every voice-agent team asks daily:
"did my prompt change make the agent better, worse, or just different?"

PROMPT_A: full compliance coaching in-prompt.
PROMPT_B: lean prompt, relying on the guardrail alone.
Expected finding: B leaks more violations to the guardrail (blocks go up)
and fails more nuanced personas -- demonstrating why defense-in-depth
needs BOTH layers.

Usage:
    python -m evals.ab_test
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.run_evals import run_suite

REPORTS = Path(__file__).parent.parent / "reports"


def compare(a: dict, b: dict) -> str:
    def agg(s):
        return {
            "pass_rate": f"{s['passed']}/{s['total']}",
            "guardrail_blocks": sum(r["guardrail_blocks"] for r in s["results"]),
            "bookings": sum(r["bookings"] for r in s["results"]),
            "escalations": sum(r["escalations"] for r in s["results"]),
            "cost_usd": s["total_cost_usd"],
        }

    A, B = agg(a), agg(b)
    lines = [
        "# Prompt A/B comparison",
        f"Run: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Metric | Prompt A (full coaching) | Prompt B (lean) |",
        "|---|---|---|",
        f"| Personas passed | {A['pass_rate']} | {B['pass_rate']} |",
        f"| Guardrail blocks (violations caught) | {A['guardrail_blocks']} | {B['guardrail_blocks']} |",
        f"| Viewings booked | {A['bookings']} | {B['bookings']} |",
        f"| Escalations to human | {A['escalations']} | {B['escalations']} |",
        f"| LLM cost | ${A['cost_usd']} | ${B['cost_usd']} |",
        "",
        "## Per-persona diff (only personas where results differ)",
        "| Persona | A | B |",
        "|---|---|---|",
    ]
    b_by_id = {r["persona"]: r for r in b["results"]}
    for ra in a["results"]:
        rb = b_by_id.get(ra["persona"])
        if rb and ra["passed"] != rb["passed"]:
            lines.append(
                f"| {ra['name']} | {'pass' if ra['passed'] else 'FAIL'} "
                f"| {'pass' if rb['passed'] else 'FAIL'} |"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Running suite with PROMPT A ===")
    a = run_suite(variant="A")
    print("\n=== Running suite with PROMPT B ===")
    b = run_suite(variant="B")

    report = compare(a, b)
    stamp = datetime.now(timezone.utc).isoformat()[:19].replace(":", "-")
    path = REPORTS / f"ab_comparison_{stamp}.md"
    path.write_text(report)
    print(f"\n{report}\n\nSaved to {path}")
