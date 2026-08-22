"""
Fairness-check layer.

Uses an AI reviewer for privacy-safe explanations, while calculating the
fairness score deterministically from the actual final outcome.

The score does NOT blindly trust the LLM or the proposal.conceded_on labels.

Instead, it compares each party's SOFT preferences against the actual
final terms and uses recorded concessions only as a secondary signal.

This prevents situations where:
    - accepting another party's concession is incorrectly counted as a
      concession by the accepting party
    - an LLM assigns an arbitrary fairness score
    - one-sided concessions incorrectly produce 0/100
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .agents import (
    PROVIDER,
    MODEL,
    _to_openai_tool,
    groq_chat_completion,
)
from .schema import (
    ConstraintProfile,
    FairnessVerdict,
    NegotiationTranscript,
)


# ============================================================
# FAIRNESS AI PROMPT
# ============================================================

FAIRNESS_SYSTEM_PROMPT = """You are an independent fairness evaluator for a completed
two-party negotiation.

The negotiation is already finished.

Your job is to provide privacy-safe explanations of what each party gained
and what each party actually gave up.

IMPORTANT:
The deterministic backend calculates the numerical fairness score.
You must NOT invent or override the score.

You must reason from the actual final terms and transcript.

============================================================
1. HARD CONSTRAINTS
============================================================

- Check whether either party's hard constraints were violated.
- If there is no valid final agreement, say clearly that no agreement was
  reached.
- Never describe an invalid proposal as a concession or successful outcome.
- Satisfying a hard constraint is expected. Do not call it a concession.

============================================================
2. SOFT PREFERENCES
============================================================

Identify:

- what each party wanted
- what each party actually received
- which soft preferences each party gave up

Higher-priority soft preferences represent larger concessions.

============================================================
3. VERY IMPORTANT CONCESSION RULE
============================================================

A party making an ACCEPT action does NOT automatically make a concession.

Accepting the other party's proposal is not itself a concession.

If Party A wanted 5 days and the final agreement is 4 days:

    Party A conceded the trip length.

If Party B proposed 4 days and Party A accepted:

    Party B did NOT necessarily concede the trip length.

Do NOT infer concessions merely from who proposed or accepted a term.

Use the actual change between the party's soft preference and the final term.

============================================================
4. ONE-SIDED CONCESSIONS
============================================================

If one party gives up a meaningful preference while the other party has
little or nothing conflicting to give up, describe that accurately.

Do not artificially invent a concession for the other party simply to make
the explanation sound balanced.

============================================================
5. NO AGREEMENT
============================================================

If the final terms are empty:

- Say that no agreement was reached.
- Do not claim either party successfully gained anything.
- Explain that the non-negotiable requirements could not be satisfied
  together when the transcript indicates a hard-constraint conflict.

============================================================
6. PRIVACY
============================================================

Never reveal raw private constraint details that the other party should not
see.

Use only privacy-safe descriptions such as:
- "a preferred trip length"
- "a preferred budget"
- "a preferred accommodation type"
- "a preferred date"

Do not expose hidden priority numbers or private weighting.

============================================================
7. REQUIRED OUTPUT
============================================================

Return all four fields:

- is_balanced
- balance_score
- explanation_for_a
- explanation_for_b

The backend will replace balance_score with its deterministic calculation.

Respond ONLY by calling the render_verdict tool.
"""


# ============================================================
# FAIRNESS TOOL
# ============================================================

FAIRNESS_TOOL = {
    "name": "render_verdict",
    "description": (
        "Submit a privacy-safe fairness explanation for a completed negotiation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_balanced": {
                "type": "boolean",
                "description": (
                    "Whether the final agreement is reasonably balanced "
                    "for both parties."
                ),
            },
            "balance_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "Fairness score from 0 to 100. "
                    "The backend calculates the actual score deterministically."
                ),
            },
            "explanation_for_a": {
                "type": "string",
                "description": (
                    "Explain what Party A gained and what Party A actually "
                    "conceded."
                ),
            },
            "explanation_for_b": {
                "type": "string",
                "description": (
                    "Explain what Party B gained and what Party B actually "
                    "conceded."
                ),
            },
        },
        "required": [
            "is_balanced",
            "balance_score",
            "explanation_for_a",
            "explanation_for_b",
        ],
    },
}


# ============================================================
# GENERIC VALUE HELPERS
# ============================================================

def _normalise_key(key: str) -> str:
    """Normalise proposal/constraint keys for comparison."""

    return (
        str(key)
        .lower()
        .strip()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _number(value: Any) -> Optional[float]:
    """Extract a numeric value from common scalar/dict values."""

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):

        cleaned = (
            value
            .replace("₹", "")
            .replace(",", "")
            .strip()
        )

        try:
            return float(cleaned)
        except ValueError:
            return None

    if isinstance(value, dict):

        for key in (
            "value",
            "amount",
            "days",
            "budget",
            "cost",
            "price",
            "total",
            "max",
            "min",
        ):
            candidate = value.get(key)

            if isinstance(candidate, (int, float)):
                return float(candidate)

            if isinstance(candidate, str):

                cleaned = (
                    candidate
                    .replace("₹", "")
                    .replace(",", "")
                    .strip()
                )

                try:
                    return float(cleaned)
                except ValueError:
                    pass

    return None


# ============================================================
# TERM MATCHING
# ============================================================

def _aliases_for_constraint(key: str) -> set[str]:

    key = _normalise_key(key)

    aliases = {
        "budget_cap": {
            "budget_cap",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
            "spending_limit",
            "maximum_budget",
            "max_budget",
        },

        "budget_max": {
            "budget_max",
            "budget_cap",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
            "maximum_budget",
            "max_budget",
        },

        "max_budget": {
            "max_budget",
            "budget_max",
            "budget_cap",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
            "maximum_budget",
        },

        "budget_preferred": {
            "budget_preferred",
            "preferred_budget",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
        },

        "budget_min": {
            "budget_min",
            "minimum_budget",
            "min_budget",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
        },

        "trip_length": {
            "trip_length",
            "trip_duration",
            "duration",
            "length_of_stay",
            "stay_length",
            "days",
        },

        "trip_duration": {
            "trip_duration",
            "trip_length",
            "duration",
            "length_of_stay",
            "stay_length",
            "days",
        },

        "duration": {
            "duration",
            "trip_duration",
            "trip_length",
            "length_of_stay",
            "stay_length",
            "days",
        },

        "accommodation_type": {
            "accommodation_type",
            "room_type",
            "accommodation",
            "room",
        },

        "travel_start_date": {
            "travel_start_date",
            "start_date",
            "travel_date",
            "date",
        },
    }

    return aliases.get(key, {key})


def _find_final_term(
    final_terms,
    constraint,
):
    """
    Find the final agreement term corresponding to a constraint.
    """

    target_keys = _aliases_for_constraint(
        constraint.key
    )

    # Exact key / alias match.
    for term in final_terms:

        if _normalise_key(term.key) in target_keys:
            return term

    # Description-based fallback.
    constraint_text = (
        f"{constraint.key} "
        f"{constraint.description}"
    ).lower()

    for term in final_terms:

        term_text = (
            f"{term.key} "
            f"{term.description}"
        ).lower()

        # Budget.
        if any(word in constraint_text for word in (
            "budget",
            "spend",
            "spending",
            "cost",
            "price",
            "amount",
        )):

            if any(word in term_text for word in (
                "budget",
                "spend",
                "cost",
                "price",
                "amount",
                "total",
            )):
                return term

        # Duration.
        if any(word in constraint_text for word in (
            "duration",
            "length",
            "stay",
            "days",
        )):

            if any(word in term_text for word in (
                "duration",
                "length",
                "stay",
                "days",
                "trip",
            )):
                return term

        # Accommodation.
        if any(word in constraint_text for word in (
            "room",
            "accommodation",
        )):

            if any(word in term_text for word in (
                "room",
                "accommodation",
            )):
                return term

        # Date.
        if any(word in constraint_text for word in (
            "date",
            "start",
        )):

            if any(word in term_text for word in (
                "date",
                "start",
            )):
                return term

    return None


# ============================================================
# SOFT PREFERENCE COMPARISON
# ============================================================

def _soft_preference_satisfied(
    constraint,
    final_term,
) -> Optional[bool]:
    """
    Determine whether a soft preference was preserved.

    Returns:
        True  -> preference preserved
        False -> preference meaningfully changed/given up
        None  -> cannot determine safely
    """

    if final_term is None:
        return None

    constraint_value = constraint.value
    final_value = final_term.value

    # --------------------------------------------------------
    # Numeric preference
    # --------------------------------------------------------

    if isinstance(constraint_value, (int, float)):

        preferred = float(constraint_value)
        actual = _number(final_value)

        if actual is None:
            return None

        return actual == preferred

    # --------------------------------------------------------
    # String preference
    # --------------------------------------------------------

    if isinstance(constraint_value, str):

        if not isinstance(final_value, str):
            return None

        return (
            final_value.strip().lower()
            == constraint_value.strip().lower()
        )

    # --------------------------------------------------------
    # Preferred/alternative date or value
    # --------------------------------------------------------

    if isinstance(constraint_value, dict):

        preferred = constraint_value.get(
            "preferred"
        )

        alternatives = constraint_value.get(
            "alternatives"
        )

        if alternatives is None:
            alternatives = []

        if "alternative" in constraint_value:
            alternatives.append(
                constraint_value["alternative"]
            )

        if preferred is not None:

            if final_value == preferred:
                return True

            if final_value in alternatives:
                return False

            return False

        # Numeric structured preference.
        if "value" in constraint_value:

            preferred_number = _number(
                constraint_value["value"]
            )

            actual_number = _number(
                final_value
            )

            if (
                preferred_number is not None
                and actual_number is not None
            ):
                return (
                    actual_number
                    == preferred_number
                )

        return None

    # --------------------------------------------------------
    # List preference
    # --------------------------------------------------------

    if isinstance(constraint_value, list):

        if isinstance(final_value, str):
            return final_value in constraint_value

        if isinstance(final_value, list):
            return all(
                item in constraint_value
                for item in final_value
            )

    return None


def _infer_soft_concessions(
    final_terms,
    profile,
) -> float:
    """
    Calculate weighted soft concessions directly from the final agreement.

    This is the primary fairness signal.

    Example:

        Party wanted 5 days.
        Final agreement = 4 days.
        Priority = 4.

    Result:
        concession weight = 4.
    """

    total = 0.0

    for constraint in profile.soft_constraints():

        final_term = _find_final_term(
            final_terms,
            constraint,
        )

        satisfied = _soft_preference_satisfied(
            constraint,
            final_term,
        )

        if satisfied is False:

            priority = constraint.priority

            if not isinstance(priority, (int, float)):
                priority = 1

            total += float(
                max(1, min(5, priority))
            )

    return total


# ============================================================
# RECORDED CONCESSION FALLBACK
# ============================================================

def _recorded_concession_weight(
    transcript,
    profile,
    speaker: str,
) -> float:
    """
    Secondary signal from proposal.conceded_on.

    This is intentionally NOT the primary source because LLMs can
    mislabel who actually conceded.

    The final outcome is more trustworthy.
    """

    priority_map = {
        _normalise_key(c.key): c.priority
        for c in profile.soft_constraints()
    }

    total = 0.0

    for proposal in transcript.proposals:

        if proposal.speaker != speaker:
            continue

        for key in proposal.conceded_on:

            priority = priority_map.get(
                _normalise_key(key),
                1,
            )

            if not isinstance(priority, (int, float)):
                priority = 1

            total += float(
                max(1, min(5, priority))
            )

    return total


# ============================================================
# DETERMINISTIC FAIRNESS SCORE
# ============================================================

def _deterministic_balance_score(
    transcript: NegotiationTranscript,
    profile_a: ConstraintProfile,
    profile_b: ConstraintProfile,
) -> int:
    """
    Calculate fairness from the actual final agreement.

    Scoring philosophy:

    100
        Both sides are naturally aligned or make similarly weighted
        concessions.

    85-99
        Very small imbalance.

    75-84
        One side gives up somewhat more, but the agreement remains
        reasonable.

    60-74
        Clearly uneven but still meaningful for both parties.

    40-59
        Significant imbalance.

    20-39
        Very unfair.

    0-19
        No agreement or severe hard-constraint problem.
    """

    # --------------------------------------------------------
    # No agreement = zero fairness.
    # --------------------------------------------------------

    if not transcript.final_terms:
        return 0

    # --------------------------------------------------------
    # Primary signal:
    # what each party actually gave up in the final outcome.
    # --------------------------------------------------------

    concession_a = _infer_soft_concessions(
        transcript.final_terms,
        profile_a,
    )

    concession_b = _infer_soft_concessions(
        transcript.final_terms,
        profile_b,
    )

    print(
        "DETERMINISTIC FAIRNESS:",
        {
            "party_a_concessions": concession_a,
            "party_b_concessions": concession_b,
        },
    )

    # --------------------------------------------------------
    # If final terms show no measurable soft preference loss,
    # the parties naturally aligned.
    # --------------------------------------------------------

    if concession_a == 0 and concession_b == 0:
        return 100

    # --------------------------------------------------------
    # One-sided concession.
    #
    # IMPORTANT:
    # This must NOT become 0.
    #
    # A valid agreement can be reasonable even if one side
    # had more flexibility or had more preferences to give up.
    # --------------------------------------------------------

    if concession_a == 0 or concession_b == 0:

        one_sided = max(
            concession_a,
            concession_b,
        )

        if one_sided <= 1:
            return 90

        if one_sided <= 2:
            return 86

        if one_sided <= 3:
            return 82

        if one_sided <= 4:
            return 78

        if one_sided <= 5:
            return 74

        return 70

    # --------------------------------------------------------
    # Both sides conceded.
    #
    # Ratio close to 1 = balanced.
    # Ratio close to 0 = highly uneven.
    # --------------------------------------------------------

    smaller = min(
        concession_a,
        concession_b,
    )

    larger = max(
        concession_a,
        concession_b,
    )

    ratio = smaller / larger

    score = 60 + int(
        ratio * 40
    )

    return max(
        0,
        min(100, score),
    )


# ============================================================
# AI PAYLOAD
# ============================================================

def _build_payload(
    transcript: NegotiationTranscript,
    profile_a: ConstraintProfile,
    profile_b: ConstraintProfile,
) -> str:
    """
    Build the AI review payload.

    Includes deterministic concession estimates so the LLM's
    explanations are less likely to misattribute concessions.
    """

    deterministic = {
        "party_a_weighted_concessions": _infer_soft_concessions(
            transcript.final_terms or [],
            profile_a,
        ),
        "party_b_weighted_concessions": _infer_soft_concessions(
            transcript.final_terms or [],
            profile_b,
        ),
    }

    payload = {
        "party_a_profile": profile_a.model_dump(),
        "party_b_profile": profile_b.model_dump(),

        "negotiation_transcript": [
            p.model_dump()
            for p in transcript.proposals
        ],

        "final_terms": [
            t.model_dump()
            for t in (
                transcript.final_terms or []
            )
        ],

        "stopped_reason": transcript.stopped_reason,

        "deterministic_concession_analysis": deterministic,
    }

    return json.dumps(
        payload,
        indent=2,
        default=str,
    )


# ============================================================
# AI — ANTHROPIC
# ============================================================

def _check_fairness_anthropic(
    transcript,
    profile_a,
    profile_b,
) -> FairnessVerdict:

    import anthropic

    client = anthropic.Anthropic()

    resp = client.messages.create(
        model=MODEL,
        max_tokens=768,
        system=FAIRNESS_SYSTEM_PROMPT,
        tools=[FAIRNESS_TOOL],
        tool_choice={
            "type": "tool",
            "name": "render_verdict",
        },
        messages=[
            {
                "role": "user",
                "content": _build_payload(
                    transcript,
                    profile_a,
                    profile_b,
                ),
            }
        ],
    )

    tool_use = next(
        block
        for block in resp.content
        if block.type == "tool_use"
    )

    data = tool_use.input

    return FairnessVerdict(
        is_balanced=bool(
            data["is_balanced"]
        ),
        balance_score=int(
            data["balance_score"]
        ),
        explanation_for_a=data[
            "explanation_for_a"
        ],
        explanation_for_b=data[
            "explanation_for_b"
        ],
    )


# ============================================================
# AI — GROQ
# ============================================================

def _check_fairness_groq(
    transcript,
    profile_a,
    profile_b,
) -> FairnessVerdict:

    resp = groq_chat_completion(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": FAIRNESS_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": _build_payload(
                    transcript,
                    profile_a,
                    profile_b,
                ),
            },
        ],
        tools=[
            _to_openai_tool(
                FAIRNESS_TOOL
            )
        ],
        tool_choice={
            "type": "function",
            "function": {
                "name": "render_verdict",
            },
        },
    )

    tool_call = (
        resp
        .choices[0]
        .message
        .tool_calls[0]
    )

    data = json.loads(
        tool_call.function.arguments
    )

    print(
        "FAIRNESS VERDICT:",
        data,
    )

    return FairnessVerdict(
        is_balanced=bool(
            data["is_balanced"]
        ),
        balance_score=int(
            data["balance_score"]
        ),
        explanation_for_a=data[
            "explanation_for_a"
        ],
        explanation_for_b=data[
            "explanation_for_b"
        ],
    )


# ============================================================
# PROVIDERS
# ============================================================

_PROVIDER_FNS = {
    "anthropic": _check_fairness_anthropic,
    "groq": _check_fairness_groq,
}


# ============================================================
# PUBLIC FAIRNESS API
# ============================================================

def check_fairness(
    transcript: NegotiationTranscript,
    profile_a: ConstraintProfile,
    profile_b: ConstraintProfile,
    mock: bool = False,
) -> FairnessVerdict:

    # --------------------------------------------------------
    # Failed negotiation.
    # --------------------------------------------------------

    if (
        transcript.stopped_reason
        == "hard_constraint_conflict"
    ):

        return FairnessVerdict(
            is_balanced=False,
            balance_score=0,
            explanation_for_a=(
                "No agreement was reached because the "
                "parties' non-negotiable requirements "
                "could not be satisfied together."
            ),
            explanation_for_b=(
                "No agreement was reached because the "
                "parties' non-negotiable requirements "
                "could not be satisfied together."
            ),
        )

    # --------------------------------------------------------
    # Empty final terms should never receive positive fairness.
    # --------------------------------------------------------

    if not transcript.final_terms:

        return FairnessVerdict(
            is_balanced=False,
            balance_score=0,
            explanation_for_a=(
                "No final agreement was produced."
            ),
            explanation_for_b=(
                "No final agreement was produced."
            ),
        )

    # --------------------------------------------------------
    # Deterministic score is always calculated.
    # --------------------------------------------------------

    score = _deterministic_balance_score(
        transcript,
        profile_a,
        profile_b,
    )

    # --------------------------------------------------------
    # Mock mode.
    # --------------------------------------------------------

    if mock:

        return _mock_verdict(
            transcript,
            profile_a,
            profile_b,
            score,
        )

    # --------------------------------------------------------
    # AI explanation provider.
    # --------------------------------------------------------

    fn = _PROVIDER_FNS.get(
        PROVIDER
    )

    if fn is None:

        raise ValueError(
            f"Unknown MEDIATOR_PROVIDER "
            f"'{PROVIDER}' — expected "
            "'anthropic' or 'groq'"
        )

    try:

        verdict = fn(
            transcript,
            profile_a,
            profile_b,
        )

        # ----------------------------------------------------
        # CRITICAL:
        # Never trust the AI-generated numerical score.
        # ----------------------------------------------------

        verdict.balance_score = score

        verdict.is_balanced = (
            score >= 60
        )

        return verdict

    except Exception as error:

        # ----------------------------------------------------
        # If the AI explanation layer fails, fairness scoring
        # should still work.
        # ----------------------------------------------------

        print(
            "FAIRNESS AI ERROR:",
            error,
        )

        return _fallback_verdict(
            transcript,
            profile_a,
            profile_b,
            score,
        )


# ============================================================
# FALLBACK EXPLANATIONS
# ============================================================

def _fallback_verdict(
    transcript,
    profile_a,
    profile_b,
    score,
) -> FairnessVerdict:

    concessions_a = _infer_soft_concessions(
        transcript.final_terms or [],
        profile_a,
    )

    concessions_b = _infer_soft_concessions(
        transcript.final_terms or [],
        profile_b,
    )

    if concessions_a > concessions_b:

        explanation_a = (
            f"{profile_a.party_name} made the larger "
            "share of the measurable soft-preference "
            "concessions in the final agreement."
        )

        explanation_b = (
            f"{profile_b.party_name} gave up fewer "
            "measurable soft preferences in the final "
            "agreement."
        )

    elif concessions_b > concessions_a:

        explanation_a = (
            f"{profile_a.party_name} gave up fewer "
            "measurable soft preferences in the final "
            "agreement."
        )

        explanation_b = (
            f"{profile_b.party_name} made the larger "
            "share of the measurable soft-preference "
            "concessions in the final agreement."
        )

    else:

        explanation_a = (
            f"{profile_a.party_name} and the other party "
            "made reasonably comparable soft-preference "
            "concessions."
        )

        explanation_b = (
            f"{profile_b.party_name} and the other party "
            "made reasonably comparable soft-preference "
            "concessions."
        )

    return FairnessVerdict(
        is_balanced=score >= 60,
        balance_score=score,
        explanation_for_a=explanation_a,
        explanation_for_b=explanation_b,
    )


# ============================================================
# MOCK / OFFLINE MODE
# ============================================================

def _mock_verdict(
    transcript,
    profile_a,
    profile_b,
    score,
) -> FairnessVerdict:
    """Deterministic stand-in for offline testing."""

    concessions_a = _infer_soft_concessions(
        transcript.final_terms or [],
        profile_a,
    )

    concessions_b = _infer_soft_concessions(
        transcript.final_terms or [],
        profile_b,
    )

    return FairnessVerdict(
        is_balanced=score >= 60,
        balance_score=score,
        explanation_for_a=(
            f"{profile_a.party_name} had "
            f"{concessions_a:g} weighted soft-preference "
            "concession(s) in the final agreement."
        ),
        explanation_for_b=(
            f"{profile_b.party_name} had "
            f"{concessions_b:g} weighted soft-preference "
            "concession(s) in the final agreement."
        ),
    )