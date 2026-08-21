"""
Private intake — turns a user's free-form description of what they want
into a structured ConstraintProfile, using the same tool-calling pattern
already proven in mediator/agents.py (and the same MEDIATOR_PROVIDER switch).

This is what makes the private intake chat screen possible: the user types
something like "I need this under 25k, I'd prefer a private room, dates are
flexible by about a week" and this turns it into HARD/SOFT constraints with
priority ranking.
"""

from __future__ import annotations

import json

from mediator.agents import PROVIDER, MODEL, _to_openai_tool
from mediator.schema import ConstraintProfile

INTAKE_SYSTEM_PROMPT = """You extract a structured negotiation brief from a person's own
description of what they want out of a negotiation (splitting costs, planning a trip,
agreeing on a rate, dividing chores, etc).

Your most important job is to distinguish NON-NEGOTIABLE requirements from PREFERENCES.

Rules:

1. HARD constraints are truly non-negotiable requirements.
   Use HARD only when the person explicitly communicates a strict requirement,
   limit, deadline, prohibition, or dealbreaker.

   Strong HARD language includes:
   - "must"
   - "have to"
   - "cannot"
   - "can't"
   - "not allowed"
   - "required"
   - "non-negotiable"
   - "dealbreaker"
   - "at most"
   - "at least" when clearly stated as a requirement
   - "no more than"
   - "no less than"
   - "must be back by"

   Examples:
   "I must have a private room" -> HARD
   "I can't spend more than 25,000" -> HARD
   "I have to be back by December 12" -> HARD
   "My budget cannot exceed 25,000" -> HARD

2. SOFT constraints are preferences that the person could potentially
   compromise on during negotiation.

   Preference language includes:
   - "prefer"
   - "would prefer"
   - "would like"
   - "I'd like"
   - "I really want"
   - "I'd rather"
   - "ideally"
   - "if possible"
   - "it would be nice"
   - "I hope"
   - "I want"
   - "I would love"

   IMPORTANT:
   "I really want a private room" is SOFT, not HARD.
   "I want at least 5 days" is SOFT unless the person clearly says
   it is mandatory or non-negotiable.
   "I'd prefer at least 5 days" is SOFT.

3. Never upgrade a preference into HARD merely because the wording is
   enthusiastic or strongly emotional. "Really want", "strongly prefer",
   and "would love" remain SOFT unless the person explicitly makes them
   non-negotiable.

4. If the person says they are flexible, the related constraint MUST be SOFT.

5. Rank SOFT constraints from 1-5 according to how strongly the person
   emphasizes them. Higher priority means more important to preserve,
   but it is still negotiable.

6. Do not invent constraints the person didn't mention. If they only
   gave two things, extract two things.

7. Preserve concrete values accurately:
   budgets, dates, durations, quantities, deadlines, etc.

8. Write a one-line scenario_summary capturing what this person is
   trying to achieve.

9. Give each constraint a short, machine-friendly key (snake_case,
   e.g. "budget_cap", "accommodation_type", "trip_length",
   "travel_dates"). Use generic reusable keys so the two parties'
   agents can match corresponding terms during negotiation.

10. Before calling the tool, internally check every constraint:
    - Did the person explicitly make this non-negotiable?
    - If yes -> HARD.
    - If it is merely something they want or prefer -> SOFT.
    - If they explicitly said they are flexible -> SOFT.

Respond ONLY by calling the `extract_profile` tool.
"""

INTAKE_TOOL = {
    "name": "extract_profile",
    "description": "Submit the structured constraint profile extracted from the user's intake text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "scenario_summary": {"type": "string"},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "description": {"type": "string"},
                        "type": {"type": "string", "enum": ["hard", "soft"]},
                        "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                        "value": {"description": "Concrete value if numeric/dated, e.g. {\"max\": 25000}"},
                    },
                    "required": ["key", "description", "type"],
                },
            },
        },
        "required": ["scenario_summary", "constraints"],
    },
}


def _extract_anthropic(party_name: str, free_text: str) -> ConstraintProfile:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=INTAKE_SYSTEM_PROMPT,
        tools=[INTAKE_TOOL],
        tool_choice={"type": "tool", "name": "extract_profile"},
        messages=[{"role": "user", "content": f"Party name: {party_name}\n\nWhat they said:\n{free_text}"}],
    )
    tool_use = next(b for b in resp.content if b.type == "tool_use")
    data = tool_use.input
    return ConstraintProfile(party_name=party_name, **data)


def _extract_groq(party_name: str, free_text: str) -> ConstraintProfile:
    from openai import OpenAI
    import os
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Party name: {party_name}\n\nWhat they said:\n{free_text}"},
        ],
        tools=[_to_openai_tool(INTAKE_TOOL)],
        tool_choice={"type": "function", "function": {"name": "extract_profile"}},
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    data = json.loads(tool_call.function.arguments)
    return ConstraintProfile(party_name=party_name, **data)


_PROVIDER_FNS = {
    "anthropic": _extract_anthropic,
    "groq": _extract_groq,
}


def _extract_mock(party_name: str, free_text: str) -> ConstraintProfile:
    """
    Deterministic stand-in for offline testing — does NOT do real extraction,
    just wraps the raw text as a single soft constraint so the room-pairing
    and negotiation flow can be tested end-to-end without any API key.
    """
    from mediator.schema import Constraint, ConstraintType
    return ConstraintProfile(
        party_name=party_name,
        scenario_summary=free_text[:80],
        constraints=[
            Constraint(key="raw_intake", description=free_text, type=ConstraintType.SOFT, priority=3)
        ],
    )


def extract_constraints(party_name: str, free_text: str, mock: bool = False) -> ConstraintProfile:
    if mock:
        return _extract_mock(party_name, free_text)
    fn = _PROVIDER_FNS.get(PROVIDER)
    if fn is None:
        raise ValueError(f"Unknown MEDIATOR_PROVIDER '{PROVIDER}' — expected 'anthropic' or 'groq'")
    return fn(party_name, free_text)
