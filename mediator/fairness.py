"""
Fairness-check layer (Phase 2) — an independent AI role, separate from
Agent A and Agent B, that reviews the final negotiated terms against BOTH
parties' full private profiles and:
  1. scores how balanced the outcome is
  2. explains, in plain language, what each side gave up / gained
  3. surfaces the one thing each party didn't know about the other's needs

Supports the same MEDIATOR_PROVIDER switch as agents.py ("anthropic" | "groq"),
so this works with whichever API key you actually have.
"""

from __future__ import annotations

import json
import os

from .agents import PROVIDER, MODEL, _to_openai_tool
from .schema import ConstraintProfile, FairnessVerdict, NegotiationTranscript

FAIRNESS_SYSTEM_PROMPT = """You are a neutral mediator reviewing a completed negotiation \
between two AI agents, each of whom represented one human party. You can see BOTH parties' \
full private constraints — something neither agent could see during the negotiation.

Your job:
1. Judge whether the final terms are genuinely balanced given each party's stated \
priorities — not just whether both agents agreed.
2. Write a short, warm, plain-language explanation for EACH party covering what they \
gained and what they gave up.
3. Identify the single most important thing about the OTHER party's needs that this \
party likely didn't know before — this is the emotional payoff of the whole product, \
so make it specific and genuine, not generic.

Be honest in your balance_score — if one side clearly gave up more, say so. Do not \
inflate the score to make the outcome look better than it is.

Respond ONLY by calling the `render_verdict` tool.
"""

FAIRNESS_TOOL = {
    "name": "render_verdict",
    "description": "Submit the fairness verdict for a completed negotiation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_balanced": {"type": "boolean"},
            "balance_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "explanation_for_a": {"type": "string"},
            "explanation_for_b": {"type": "string"},
            "what_a_didnt_know": {"type": "string"},
            "what_b_didnt_know": {"type": "string"},
        },
        "required": [
            "is_balanced", "balance_score",
            "explanation_for_a", "explanation_for_b",
            "what_a_didnt_know", "what_b_didnt_know",
        ],
    },
}


def _build_payload(transcript: NegotiationTranscript, profile_a: ConstraintProfile, profile_b: ConstraintProfile) -> str:
    payload = {
        "party_a_profile": profile_a.model_dump(),
        "party_b_profile": profile_b.model_dump(),
        "negotiation_transcript": [p.model_dump() for p in transcript.proposals],
        "final_terms": [t.model_dump() for t in (transcript.final_terms or [])],
        "stopped_reason": transcript.stopped_reason,
    }
    return json.dumps(payload, indent=2)


def _check_fairness_anthropic(transcript, profile_a, profile_b) -> FairnessVerdict:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=FAIRNESS_SYSTEM_PROMPT,
        tools=[FAIRNESS_TOOL],
        tool_choice={"type": "tool", "name": "render_verdict"},
        messages=[{"role": "user", "content": _build_payload(transcript, profile_a, profile_b)}],
    )
    tool_use = next(b for b in resp.content if b.type == "tool_use")
    return FairnessVerdict(**tool_use.input)


def _check_fairness_groq(transcript, profile_a, profile_b) -> FairnessVerdict:
    from openai import OpenAI
    client = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": FAIRNESS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_payload(transcript, profile_a, profile_b)},
        ],
        tools=[_to_openai_tool(FAIRNESS_TOOL)],
        tool_choice={"type": "function", "function": {"name": "render_verdict"}},
    )
    tool_call = resp.choices[0].message.tool_calls[0]
    data = json.loads(tool_call.function.arguments)
    return FairnessVerdict(**data)


_PROVIDER_FNS = {
    "anthropic": _check_fairness_anthropic,
    "groq": _check_fairness_groq,
}


def check_fairness(
    transcript: NegotiationTranscript,
    profile_a: ConstraintProfile,
    profile_b: ConstraintProfile,
    mock: bool = False,
) -> FairnessVerdict:
    if mock:
        return _mock_verdict(transcript, profile_a, profile_b)

    fn = _PROVIDER_FNS.get(PROVIDER)
    if fn is None:
        raise ValueError(f"Unknown MEDIATOR_PROVIDER '{PROVIDER}' — expected 'anthropic' or 'groq'")
    return fn(transcript, profile_a, profile_b)


def _mock_verdict(transcript, profile_a, profile_b) -> FairnessVerdict:
    """Deterministic stand-in for offline loop testing."""
    conceded_by_a = sum(1 for p in transcript.proposals if p.speaker == "agent_a" and p.conceded_on)
    conceded_by_b = sum(1 for p in transcript.proposals if p.speaker == "agent_b" and p.conceded_on)
    total = max(conceded_by_a + conceded_by_b, 1)
    balance = int(100 - abs(conceded_by_a - conceded_by_b) / total * 100)

    return FairnessVerdict(
        is_balanced=balance >= 60,
        balance_score=balance,
        explanation_for_a=f"{profile_a.party_name} held firm on hard constraints and conceded on {conceded_by_a} lower-priority item(s).",
        explanation_for_b=f"{profile_b.party_name} held firm on hard constraints and conceded on {conceded_by_b} lower-priority item(s).",
        what_a_didnt_know=f"{profile_b.party_name} had a hard constraint that made early agreement valuable.",
        what_b_didnt_know=f"{profile_a.party_name} had a hard constraint that made early agreement valuable.",
    )
