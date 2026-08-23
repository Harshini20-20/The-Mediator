"""
NegotiatingAgent — wraps one party's private ConstraintProfile and talks to
an LLM to produce the next Proposal in the negotiation.

Supports:
- Anthropic
- Groq
- Mock/offline mode

Groq supports automatic API-key failover:

    GROQ_API_KEY
        ↓
    try primary key
        ↓
    failure / rate limit
        ↓
    GROQ_API_KEY_BACKUP
        ↓
    try backup key

The backup key is only used when the primary request fails.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
import os
from dotenv import load_dotenv

load_dotenv()
from .schema import (
    ConstraintProfile,
    Proposal,
    ProposalAction,
    ProposalTerm,
)


# ============================================================
# PROVIDER CONFIGURATION
# ============================================================

PROVIDER = os.environ.get(
    "MEDIATOR_PROVIDER",
    "groq",
)

_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5",
    "groq": "openai/gpt-oss-20b",
}

MODEL = os.environ.get(
    "MEDIATOR_MODEL",
    _DEFAULT_MODELS.get(
        PROVIDER,
        "llama-3.3-70b-versatile",
    ),
)


# ============================================================
# GROQ API KEYS
# ============================================================

# Primary key.
#
# Keep the actual key in your environment / .env file.
# Do not hard-code it into source code.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BACKUP_KEY = os.getenv("GROQ_BACKUP_KEY")

def get_groq_api_keys() -> list[str]:
    """
    Return configured Groq keys in priority order.

    Primary key is always tried first.
    Backup key is only tried if the primary fails.
    """

    keys = []

    if GROQ_API_KEY:
        keys.append(GROQ_API_KEY)

    if GROQ_BACKUP_KEY:
        keys.append(GROQ_BACKUP_KEY)

    return keys


def get_groq_client(api_key: str):
    """
    Create an OpenAI-compatible client connected to Groq.
    """

    from openai import OpenAI

    return OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )


def is_groq_retryable_error(error: Exception) -> bool:
    """
    Decide whether another Groq API key should be attempted.

    Retry/failover for:
    - 401 authentication errors
    - 429 rate limits
    - temporary server errors
    - service unavailable errors
    """

    message = str(error).lower()

    retryable_terms = [
        "401",
        "429",
        "rate limit",
        "rate_limit_exceeded",
        "tokens per day",
        "authentication",
        "unauthorized",
        "500",
        "502",
        "503",
        "504",
        "service unavailable",
        "temporarily unavailable",
    ]

    return any(
        term in message
        for term in retryable_terms
    )


def groq_chat_completion(
    *,
    model: str,
    messages: list,
    tools: list | None = None,
    tool_choice: dict | None = None,
):
    """
    Execute a Groq chat completion with automatic API-key failover.

    Primary key is tried first.
    If it fails with a retryable error such as 429/rate-limit,
    the backup key is tried automatically.
    """

    keys = get_groq_api_keys()

    if not keys:
        raise RuntimeError(
            "No Groq API key configured. "
            "Set GROQ_API_KEY or GROQ_API_KEY_BACKUP."
        )

    kwargs = {
        "model": model,
        "messages": messages,
    }

    if tools is not None:
        kwargs["tools"] = tools

    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    last_error = None

    for index, api_key in enumerate(keys):

        key_name = "primary" if index == 0 else "backup"

        try:
            print(
                f"Trying Groq {key_name} API key..."
            )

            client = get_groq_client(api_key)

            response = client.chat.completions.create(
                **kwargs
            )

            print(
                f"Groq request succeeded using {key_name} API key."
            )

            return response

        except Exception as error:

            last_error = error

            print(
                f"Groq {key_name} API key failed: "
                f"{type(error).__name__}: {error}"
            )

            # If this was the primary key and another key exists,
            # try the backup only for retryable failures.
            if index < len(keys) - 1:

                if is_groq_retryable_error(error):

                    print(
                        "Retryable Groq error detected. "
                        "Switching to backup API key..."
                    )

                    continue

                # Non-retryable error: don't waste the backup key.
                raise

    # Every configured key failed.
    raise last_error


# ============================================================
# AGENT SYSTEM PROMPT
# ============================================================

AGENT_SYSTEM_PROMPT = """You are a negotiation agent representing ONE party in a two-party
negotiation. You have never seen the other party's private constraints — only what their
agent reveals to you through proposals.

Your job:

1. Advocate firmly for your principal's HARD constraints — never propose or accept terms
   that violate them.

2. Be willing to trade away low-priority SOFT preferences to reach agreement faster.

3. Never reveal your principal's priority weights directly — negotiate as a human advocate
   would, not by reciting numbers.

4. Converge steadily. Every round, either accept, concede on something, or narrow the gap —
   never repeat the same offer twice in a row.

5. EVERY term you submit must state the concrete offer, not just repeat the constraint's name.

Bad:
{"key": "trip_length", "description": "Trip length"}

Good:
{"key": "trip_length", "description": "4-day trip", "value": 4}

Always populate `value` with the actual number/date/amount/choice being offered.
Never leave it empty.

IMPORTANT VALUE FORMAT RULES:

- trip_length → use a plain number, e.g. 3
- budget_cap → use a plain number, e.g. 18000
- budget_preferred → use a plain number, e.g. 17000
- date/start date → use a plain ISO date string, e.g. "2026-12-13"
- accommodation_type → use exactly "private" or "shared"

The `value` field must ALWAYS be a simple string, number, or boolean.

Never use nested objects.

Never use:
{"days": 3}
{"duration_days": 3}
{"amount": 18000}
{"preference": "private_room"}
{"start_range": {"start": "...", "end": "..."}}

Use:
3
18000
"2026-12-13"
"private"
"shared"

The `description` should contain the human-readable concrete offer,
while `value` contains only the simple machine-readable value.

6. Hard round limits — these are not suggestions:

   - Round 6: you MUST set action to "concede" — give ground on at least one SOFT item,
     even if it's your lowest-priority one.

   - Round 7-8: you MUST set action to "accept" — take the other side's last proposal
     as-is. Do not propose again. A deal now beats no deal.

Respond ONLY by calling the `make_proposal` tool.
Never respond in plain text.
"""


# ============================================================
# PROPOSAL TOOL
# ============================================================

PROPOSAL_TOOL = {
    "name": "make_proposal",
    "description": (
        "Submit your next move in the negotiation. "
        "Every term must contain a concrete, simple value."
    ),
    "input_schema": {
        "type": "object",
        "properties": {

            "action": {
                "type": "string",
                "enum": [
                    "propose",
                    "accept",
                    "concede",
                ],
                "description": (
                    "propose = new/counter offer, "
                    "accept = take the other side's last offer as-is, "
                    "concede = accept while explicitly giving ground "
                    "on one term"
                ),
            },

            "terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {

                        "key": {
                            "type": "string",
                            "description": (
                                "Canonical constraint key, such as "
                                "budget_cap, trip_length, "
                                "travel_start_date, or "
                                "accommodation_type."
                            ),
                        },

                        "description": {
                            "type": "string",
                            "description": (
                                "State the concrete offer. "
                                "Examples: '3-day trip', "
                                "'INR 18,000 total budget', "
                                "'December 13, 2026', "
                                "'private room'."
                            ),
                        },

                        "value": {
                            "type": [
                                "string",
                                "number",
                                "boolean"
                            ],
                            "description": (
                                "The concrete value being offered. "
                                "Use a simple scalar only. "
                                "For trip length use a number such as 3. "
                                "For budget use a number such as 18000. "
                                "For dates use YYYY-MM-DD. "
                                "For accommodation use 'private' or 'shared'. "
                                "Do NOT use nested objects."
                            ),
                        },

                    },

                    "required": [
                        "key",
                        "description",
                        "value",
                    ],

                    "additionalProperties": False,
                },
            },

            "rationale": {
                "type": "string",
                "description": (
                    "One or two sentences explaining this move."
                ),
            },

            "conceded_on": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": (
                    "Keys of terms you gave ground on this round. "
                    "Use an empty array if none."
                ),
            },

        },

        "required": [
            "action",
            "terms",
            "rationale",
            "conceded_on",
        ],

        "additionalProperties": False,
    },
}


def _to_openai_tool(
    anthropic_style_tool: dict,
) -> dict:
    """
    Converts an Anthropic-format tool definition into
    OpenAI/Groq function-calling format.
    """

    return {
        "type": "function",
        "function": {
            "name": anthropic_style_tool["name"],
            "description": anthropic_style_tool["description"],
            "parameters": anthropic_style_tool["input_schema"],
        },
    }


# ============================================================
# BASE AGENT
# ============================================================

class BaseAgent(ABC):

    def __init__(
        self,
        profile: ConstraintProfile,
        agent_id: str,
    ):
        self.profile = profile
        self.agent_id = agent_id

    @abstractmethod
    def next_move(
        self,
        round_number: int,
        other_last: Proposal | None,
    ) -> Proposal:
        ...

    def _profile_brief(self) -> str:

        lines = [
            f"You represent: {self.profile.party_name}",
            f"Their goal: {self.profile.scenario_summary}",
            "",
            "HARD constraints (never violate):",
        ]

        for constraint in self.profile.hard_constraints():
            lines.append(
                f"  - {constraint.key}: "
                f"{constraint.description} "
                f"(value={constraint.value})"
            )

        lines.append("")
        lines.append(
            "SOFT preferences "
            "(ranked, highest priority first):"
        )

        for constraint in self.profile.soft_constraints():
            lines.append(
                f"  - [priority {constraint.priority}/5] "
                f"{constraint.key}: "
                f"{constraint.description} "
                f"(value={constraint.value})"
            )

        return "\n".join(lines)

    def _history_note(
    self,
    round_number: int,
    other_last: Proposal | None,
) -> str:

        if not other_last:
            return (
                "This is the opening move — propose something "
                "reasonable based on your own priorities. "
                "Include concrete values for every term."
            )

        # IMPORTANT PRIVACY RULE:
        # The other agent's private rationale is NEVER exposed.
        # Only the public proposal terms and action are visible.
        public_terms = [
            {
                "key": term.key,
                "description": term.description,
                "value": term.value,
            }
            for term in other_last.terms
        ]

        note = (
            f"The other party's agent just moved "
            f"(round {other_last.round_number}).\n"
            f"  action={other_last.action.value}\n"
            f"  terms={json.dumps(public_terms)}\n"
            f"  conceded_on={other_last.conceded_on}\n\n"
            f"You are now on round {round_number} of a max of 8."
        )

        if round_number == 6:
            note += (
                "\n\nROUND 6 RULE: you MUST set "
                "action='concede' this round and give "
                "ground on at least one SOFT item."
            )

        elif round_number >= 7:
            note += (
                "\n\nROUND 7-8 RULE: you MUST set "
                "action='accept' this round, taking the "
                "other side's last proposal exactly as terms. "
                "Do not propose again."
            )

        return note

    def _parse_result(
        self,
        round_number: int,
        data: dict,
    ) -> Proposal:

        return Proposal(
            round_number=round_number,
            speaker=self.agent_id,
            action=ProposalAction(data["action"]),
            terms=[
                ProposalTerm(**term)
                for term in data["terms"]
            ],
            rationale=data["rationale"],
            conceded_on=data.get(
                "conceded_on",
                [],
            ),
        )


# ============================================================
# ANTHROPIC AGENT
# ============================================================

class AnthropicLiveAgent(BaseAgent):
    """
    Calls the Claude API.
    """

    def __init__(
        self,
        profile: ConstraintProfile,
        agent_id: str,
    ):
        super().__init__(
            profile,
            agent_id,
        )

        import anthropic

        self._client = anthropic.Anthropic()

    def next_move(
        self,
        round_number: int,
        other_last: Proposal | None,
    ) -> Proposal:

        resp = self._client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=AGENT_SYSTEM_PROMPT,
            tools=[PROPOSAL_TOOL],
            tool_choice={
                "type": "tool",
                "name": "make_proposal",
            },
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"{self._profile_brief()}\n\n"
                        f"{self._history_note(round_number, other_last)}"
                    ),
                }
            ],
        )

        tool_use = next(
            block
            for block in resp.content
            if block.type == "tool_use"
        )

        return self._parse_result(
            round_number,
            tool_use.input,
        )


# ============================================================
# GROQ AGENT WITH FAILOVER
# ============================================================

class GroqLiveAgent(BaseAgent):
    """
    Calls Groq's OpenAI-compatible chat completions API.

    Automatically fails over from:

        GROQ_API_KEY

    to:

        GROQ_API_KEY_BACKUP

    when the primary key receives a retryable failure such as
    429 rate limiting.
    """

    def __init__(
        self,
        profile: ConstraintProfile,
        agent_id: str,
    ):
        super().__init__(
            profile,
            agent_id,
        )

        # Validate that at least one key exists early.
        if not get_groq_api_keys():
            raise RuntimeError(
                "No Groq API key configured. "
                "Set GROQ_API_KEY or GROQ_API_KEY_BACKUP."
            )

    def next_move(
        self,
        round_number: int,
        other_last: Proposal | None,
    ) -> Proposal:

        resp = groq_chat_completion(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": AGENT_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": (
                        f"{self._profile_brief()}\n\n"
                        f"{self._history_note(round_number, other_last)}"
                    ),
                },
            ],
            tools=[
                _to_openai_tool(PROPOSAL_TOOL)
            ],
            tool_choice={
                "type": "function",
                "function": {
                    "name": "make_proposal"
                },
            },
        )

        tool_call = (
            resp.choices[0]
            .message
            .tool_calls[0]
        )

        data = json.loads(
            tool_call.function.arguments
        )

        return self._parse_result(
            round_number,
            data,
        )


# ============================================================
# MOCK AGENT
# ============================================================

class MockAgent(BaseAgent):
    """
    Deterministic stand-in for offline testing of the
    negotiation LOOP.

    Does not test negotiation quality.

    Concedes one soft preference per round after round 2,
    and accepts by round 4 if the other side has conceded too.
    """

    def next_move(
        self,
        round_number: int,
        other_last: Proposal | None,
    ) -> Proposal:

        softs = self.profile.soft_constraints()
        hards = self.profile.hard_constraints()

        if (
            other_last
            and other_last.conceded_on
            and round_number >= 3
        ):
            return Proposal(
                round_number=round_number,
                speaker=self.agent_id,
                action=ProposalAction.ACCEPT,
                terms=other_last.terms,
                rationale=(
                    f"{self.profile.party_name}'s agent "
                    "accepts — the other side already gave ground."
                ),
                conceded_on=[],
            )

        terms = [
            ProposalTerm(
                key=constraint.key,
                description=constraint.description,
                value=constraint.value,
            )
            for constraint in hards
        ]

        conceded = []

        if round_number > 1 and softs:

            lowest = softs[-1]

            conceded = [
                lowest.key
            ]

            terms.append(
                ProposalTerm(
                    key=lowest.key,
                    description=(
                        f"(conceded) "
                        f"{lowest.description}"
                    ),
                    value=lowest.value,
                )
            )

            for constraint in softs[:-1]:
                terms.append(
                    ProposalTerm(
                        key=constraint.key,
                        description=constraint.description,
                        value=constraint.value,
                    )
                )

        else:

            terms.extend(
                ProposalTerm(
                    key=constraint.key,
                    description=constraint.description,
                    value=constraint.value,
                )
                for constraint in softs
            )

        return Proposal(
            round_number=round_number,
            speaker=self.agent_id,
            action=ProposalAction.PROPOSE,
            terms=terms,
            rationale=(
                f"{self.profile.party_name}'s agent holds firm "
                f"on hard constraints, "
                f"{'conceding on ' + conceded[0] if conceded else 'opening with full preferences'}."
            ),
            conceded_on=conceded,
        )


# ============================================================
# PROVIDER MAP
# ============================================================

_PROVIDER_AGENTS = {
    "anthropic": AnthropicLiveAgent,
    "groq": GroqLiveAgent,
}


def make_agent(
    profile: ConstraintProfile,
    agent_id: str,
    mock: bool = False,
) -> BaseAgent:

    if mock:
        return MockAgent(
            profile,
            agent_id,
        )

    agent_cls = _PROVIDER_AGENTS.get(
        PROVIDER
    )

    if agent_cls is None:
        raise ValueError(
            f"Unknown MEDIATOR_PROVIDER '{PROVIDER}' "
            "— expected 'anthropic' or 'groq'"
        )

    return agent_cls(
        profile,
        agent_id,
    )