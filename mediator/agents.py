"""
NegotiatingAgent — wraps one party's private ConstraintProfile and talks to
an LLM to produce the next Proposal in the negotiation.

Modes:
- LIVE (provider="anthropic"): calls the Claude API with tool use.
- LIVE (provider="groq"):      calls Groq's OpenAI-compatible API with
                                 function calling. Same tool schema, just a
                                 different transport — this is what lets you
                                 keep building today without an Anthropic key.
- MOCK: a deterministic stand-in that concedes gradually. Use this to test
        the negotiation LOOP LOGIC (round counting, stopping conditions,
        hard-constraint checks) without burning API calls or needing any
        key at all — validate this first, always.

Provider + model are read from environment variables so you can switch
without touching code:
    MEDIATOR_PROVIDER = "anthropic" | "groq"   (default: "groq")
    MEDIATOR_MODEL     = model string for whichever provider is active
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

from .schema import ConstraintProfile, Proposal, ProposalAction, ProposalTerm

PROVIDER = os.environ.get("MEDIATOR_PROVIDER", "groq")  # "anthropic" | "groq"

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "groq": "openai/gpt-oss-120b",
}
MODEL = os.environ.get("MEDIATOR_MODEL", _DEFAULT_MODELS.get(PROVIDER, "llama-3.3-70b-versatile"))

AGENT_SYSTEM_PROMPT = """You are a negotiation agent representing ONE party in a two-party \
negotiation. You have never seen the other party's private constraints — only what their \
agent reveals to you through proposals.

Your job:
1. Advocate firmly for your principal's HARD constraints — never propose or accept terms \
that violate them.
2. Be willing to trade away low-priority SOFT preferences to reach agreement faster.
3. Never reveal your principal's priority weights directly — negotiate as a human advocate \
would, not by reciting numbers.
4. Converge steadily. Every round, either accept, concede on something, or narrow the gap — \
never repeat the same offer twice in a row.
5. EVERY term you submit must state the concrete offer, not just repeat the constraint's \
name. Bad: {"key": "trip_length", "description": "Trip length"}. Good: {"key": "trip_length", \
"description": "4-day trip", "value": {"days": 4}}. Always populate `value` with the actual \
number/date/amount being offered — never leave it empty when the term is numeric or dated.
6. Hard round limits — these are not suggestions:
   - Round 6: you MUST set action to "concede" — give ground on at least one SOFT item, \
even if it's your lowest-priority one.
   - Round 7-8: you MUST set action to "accept" — take the other side's last proposal as-is. \
Do not propose again. A deal now beats no deal.

Respond ONLY by calling the `make_proposal` tool. Never respond in plain text.
"""

# Single source of truth for the tool schema, in Anthropic's format.
# _to_openai_tool() below converts it for Groq/OpenAI-style calls.
PROPOSAL_TOOL = {
    "name": "make_proposal",
    "description": "Submit your next move in the negotiation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["propose", "accept", "concede"],
                "description": "propose = new/counter offer, accept = take the other side's last offer as-is, concede = accept while explicitly giving ground on one term",
            },
            "terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "description": {"type": "string", "description": "Must state the CONCRETE offer, e.g. '4-day trip' or 'INR 30,000 budget' — never just the constraint's name"},
                        "value": {
                            "description": "The actual number/date/amount/choice being offered, e.g. {\"days\": 4} or \"private room\" — populate whenever the term has a concrete value",
                        },
                    },
                    "required": ["key", "description"],
                },
            },
            "rationale": {"type": "string", "description": "One or two sentences explaining this move"},
            "conceded_on": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keys of terms you gave ground on this round (empty if none)",
            },
        },
        "required": ["action", "terms", "rationale", "conceded_on"],
    },
}


def _to_openai_tool(anthropic_style_tool: dict) -> dict:
    """Converts an Anthropic-format tool def into OpenAI/Groq function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": anthropic_style_tool["name"],
            "description": anthropic_style_tool["description"],
            "parameters": anthropic_style_tool["input_schema"],
        },
    }


class BaseAgent(ABC):
    def __init__(self, profile: ConstraintProfile, agent_id: str):
        self.profile = profile
        self.agent_id = agent_id  # "agent_a" | "agent_b"

    @abstractmethod
    def next_move(self, round_number: int, other_last: Proposal | None) -> Proposal:
        ...

    def _profile_brief(self) -> str:
        lines = [f"You represent: {self.profile.party_name}", f"Their goal: {self.profile.scenario_summary}", "", "HARD constraints (never violate):"]
        for c in self.profile.hard_constraints():
            lines.append(f"  - {c.key}: {c.description} (value={c.value})")
        lines.append("")
        lines.append("SOFT preferences (ranked, highest priority first):")
        for c in self.profile.soft_constraints():
            lines.append(f"  - [priority {c.priority}/5] {c.key}: {c.description} (value={c.value})")
        return "\n".join(lines)

    def _history_note(self, round_number: int, other_last: Proposal | None) -> str:
        if not other_last:
            return "This is the opening move — propose something reasonable based on your priorities. Include concrete values for every term."
        note = (
            f"The other party's agent just moved (round {other_last.round_number}):\n"
            f"  action={other_last.action.value}\n"
            f"  terms={json.dumps([t.model_dump() for t in other_last.terms])}\n"
            f"  rationale: {other_last.rationale}\n"
            f"  conceded_on: {other_last.conceded_on}\n\n"
            f"You are now on round {round_number} of a max of 8."
        )
        if round_number == 6:
            note += "\n\nROUND 6 RULE: you MUST set action='concede' this round and give ground on at least one SOFT item."
        elif round_number >= 7:
            note += "\n\nROUND 7-8 RULE: you MUST set action='accept' this round, taking the other side's last proposal exactly as terms. Do not propose again."
        return note

    def _parse_result(self, round_number: int, data: dict) -> Proposal:
        return Proposal(
            round_number=round_number,
            speaker=self.agent_id,
            action=ProposalAction(data["action"]),
            terms=[ProposalTerm(**t) for t in data["terms"]],
            rationale=data["rationale"],
            conceded_on=data.get("conceded_on", []),
        )


class AnthropicLiveAgent(BaseAgent):
    """Calls the Claude API. Requires ANTHROPIC_API_KEY in the environment."""

    def __init__(self, profile: ConstraintProfile, agent_id: str):
        super().__init__(profile, agent_id)
        import anthropic  # deferred import so mock/groq mode never requires this package
        self._client = anthropic.Anthropic()

    def next_move(self, round_number: int, other_last: Proposal | None) -> Proposal:
        resp = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=AGENT_SYSTEM_PROMPT,
            tools=[PROPOSAL_TOOL],
            tool_choice={"type": "tool", "name": "make_proposal"},
            messages=[{"role": "user", "content": f"{self._profile_brief()}\n\n{self._history_note(round_number, other_last)}"}],
        )
        tool_use = next(b for b in resp.content if b.type == "tool_use")
        return self._parse_result(round_number, tool_use.input)


class GroqLiveAgent(BaseAgent):
    """
    Calls Groq's OpenAI-compatible chat completions API. Requires
    GROQ_API_KEY in the environment. Uses the `openai` package pointed at
    Groq's base URL — no separate SDK needed.
    """

    def __init__(self, profile: ConstraintProfile, agent_id: str):
        super().__init__(profile, agent_id)
        from openai import OpenAI  # deferred import
        self._client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )

    def next_move(self, round_number: int, other_last: Proposal | None) -> Proposal:
        resp = self._client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"{self._profile_brief()}\n\n{self._history_note(round_number, other_last)}"},
            ],
            tools=[_to_openai_tool(PROPOSAL_TOOL)],
            tool_choice={"type": "function", "function": {"name": "make_proposal"}},
        )
        tool_call = resp.choices[0].message.tool_calls[0]
        data = json.loads(tool_call.function.arguments)
        return self._parse_result(round_number, data)


class MockAgent(BaseAgent):
    """
    Deterministic stand-in for offline testing of the negotiation LOOP —
    not the negotiation quality. Concedes one soft preference per round
    after round 2, and accepts by round 4 if the other side has conceded too.
    """

    def next_move(self, round_number: int, other_last: Proposal | None) -> Proposal:
        softs = self.profile.soft_constraints()
        hards = self.profile.hard_constraints()

        if other_last and other_last.conceded_on and round_number >= 3:
            return Proposal(
                round_number=round_number,
                speaker=self.agent_id,
                action=ProposalAction.ACCEPT,
                terms=other_last.terms,
                rationale=f"{self.profile.party_name}'s agent accepts — the other side already gave ground.",
                conceded_on=[],
            )

        terms = [ProposalTerm(key=c.key, description=c.description, value=c.value) for c in hards]
        conceded = []
        if round_number > 1 and softs:
            lowest = softs[-1]
            conceded = [lowest.key]
            terms.append(ProposalTerm(key=lowest.key, description=f"(conceded) {lowest.description}", value=lowest.value))
            for c in softs[:-1]:
                terms.append(ProposalTerm(key=c.key, description=c.description, value=c.value))
        else:
            terms.extend(ProposalTerm(key=c.key, description=c.description, value=c.value) for c in softs)

        return Proposal(
            round_number=round_number,
            speaker=self.agent_id,
            action=ProposalAction.PROPOSE,
            terms=terms,
            rationale=f"{self.profile.party_name}'s agent holds firm on hard constraints, "
                      f"{'conceding on ' + conceded[0] if conceded else 'opening with full preferences'}.",
            conceded_on=conceded,
        )


_PROVIDER_AGENTS = {
    "anthropic": AnthropicLiveAgent,
    "groq": GroqLiveAgent,
}


def make_agent(profile: ConstraintProfile, agent_id: str, mock: bool = False) -> BaseAgent:
    if mock:
        return MockAgent(profile, agent_id)
    agent_cls = _PROVIDER_AGENTS.get(PROVIDER)
    if agent_cls is None:
        raise ValueError(f"Unknown MEDIATOR_PROVIDER '{PROVIDER}' — expected 'anthropic' or 'groq'")
    return agent_cls(profile, agent_id)
