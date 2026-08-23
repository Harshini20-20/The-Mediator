"""
The negotiation loop controller.

Runs Agent A and Agent B through bounded negotiation rounds while
enforcing deterministic hard-constraint safety.

The LLM is responsible for negotiation quality.
This module is responsible for making sure the final agreement
never violates either party's HARD constraints.
"""

from __future__ import annotations
from datetime import datetime
from typing import Callable, Optional
import re
from .agents import BaseAgent
from .schema import (
    Constraint,
    ConstraintProfile,
    NegotiationTranscript,
    Proposal,
    ProposalAction,
    ProposalTerm,
)


MAX_ROUNDS = 8
FORCE_ACCEPT_ROUND = 7


# ============================================================
# VALUE HELPERS
# ============================================================

def _number(value):
    """
    Extract a numeric value from common structured values,
    including strings such as "3-day trip", "3 days", "₹20,000",
    and dictionaries such as {"days": 3}.
    """

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        cleaned = (
            value
            .replace("₹", "")
            .replace(",", "")
            .strip()
        )

        # Direct numeric string.
        try:
            return float(cleaned)
        except ValueError:
            pass

        # Extract the first number from strings such as:
        # "3-day trip"
        # "3 days"
        # "₹20,000 total"
        match = re.search(
            r"-?\d+(?:\.\d+)?",
            cleaned,
        )

        if match:
            try:
                return float(match.group())
            except ValueError:
                pass

    if isinstance(value, dict):

        # Prefer semantic numeric fields.
        for key in (
            "days",
            "hours",
            "weeks",
            "amount",
            "budget",
            "total",
            "price",
            "cost",
            "value",
            "max",
            "min",
        ):

            candidate = value.get(key)

            if candidate is None:
                continue

            number = _number(candidate)

            if number is not None:
                return number

    return None
from datetime import datetime

def _date(value):
    """Extract a date from an ISO string or a dict wrapping one."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip()).date()
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("date", "value", "by", "deadline"):
            candidate = value.get(key)
            if candidate is not None:
                d = _date(candidate)
                if d is not None:
                    return d
    return None

def _term_value(term: ProposalTerm):
    """Return the concrete value carried by a proposal term."""
    return term.value


# ============================================================
# TERM KEY MATCHING
# ============================================================

def _normalise_key(key: str) -> str:
    """
    Normalise machine-friendly keys so equivalent proposal terms
    can still be matched to a hard constraint.
    """

    return (
        key.lower()
        .strip()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _find_term(
    terms: list[ProposalTerm],
    key: str,
) -> Optional[ProposalTerm]:
    """
    Find a proposal term by its machine-readable key.

    Also supports common aliases used by the trip-negotiation
    agents, especially for budget and trip duration.
    """

    target = _normalise_key(key)

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
        },

        "max_budget": {
            "max_budget",
            "budget_cap",
            "budget",
            "total_budget",
            "total_cost",
            "cost",
            "price",
            "amount",
            "maximum_budget",
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
    }

    accepted_keys = aliases.get(target, {target})

    for term in terms:
        term_key = _normalise_key(term.key)

        if term_key in accepted_keys:
            return term

    return None


# ============================================================
# HARD-CONSTRAINT VALIDATION
# ============================================================

def _satisfies_hard_constraint(
    constraint: Constraint,
    term: ProposalTerm,
) -> bool:
    """
    Deterministically validate a proposal term against one HARD
    constraint.

    IMPORTANT:
    We never allow an unsupported concrete value to silently pass.
    """

    constraint_value = constraint.value
    proposed_value = _term_value(term)

    print("DEBUG CONSTRAINT:", constraint_value)
    print("DEBUG PROPOSAL:", proposed_value)

    # --------------------------------------------------------
    # Numeric maximum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "max" in constraint_value:

        maximum = constraint_value["max"]
        proposed_number = _number(proposed_value)

        if (
            proposed_number is not None
            and isinstance(maximum, (int, float))
        ):
            return proposed_number <= float(maximum)

        # We have a hard maximum but cannot validate the proposal.
        return False

    # --------------------------------------------------------
    # Numeric minimum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "min" in constraint_value:

        minimum = constraint_value["min"]
        proposed_number = _number(proposed_value)

        if (
            proposed_number is not None
            and isinstance(minimum, (int, float))
        ):
            return proposed_number >= float(minimum)

        return False

    # --------------------------------------------------------
    # Explicit days minimum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "min_days" in constraint_value:

        minimum_days = constraint_value["min_days"]
        proposed_days = _number(proposed_value)

        if proposed_days is not None:
            return proposed_days >= float(minimum_days)

        return False

    # --------------------------------------------------------
    # Explicit days maximum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "max_days" in constraint_value:

        maximum_days = constraint_value["max_days"]
        proposed_days = _number(proposed_value)

        if proposed_days is not None:
            return proposed_days <= float(maximum_days)

        return False

    # --------------------------------------------------------
    # Explicit hours minimum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "min_hours" in constraint_value:

        minimum_hours = constraint_value["min_hours"]
        proposed_hours = _number(proposed_value)

        if proposed_hours is not None:
            return proposed_hours >= float(minimum_hours)

        return False

    # --------------------------------------------------------
    # Explicit hours maximum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "max_hours" in constraint_value:

        maximum_hours = constraint_value["max_hours"]
        proposed_hours = _number(proposed_value)

        if proposed_hours is not None:
            return proposed_hours <= float(maximum_hours)

        return False

    # --------------------------------------------------------
    # Explicit weeks minimum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "min_weeks" in constraint_value:

        minimum_weeks = constraint_value["min_weeks"]
        proposed_weeks = _number(proposed_value)

        if proposed_weeks is not None:
            return proposed_weeks >= float(minimum_weeks)

        return False

    # --------------------------------------------------------
    # Explicit weeks maximum
    # --------------------------------------------------------

    if isinstance(constraint_value, dict) and "max_weeks" in constraint_value:

        maximum_weeks = constraint_value["max_weeks"]
        proposed_weeks = _number(proposed_value)

        if proposed_weeks is not None:
            return proposed_weeks <= float(maximum_weeks)

        return False

    # --------------------------------------------------------
    # Simple scalar equality
    # --------------------------------------------------------

    if isinstance(constraint_value, (int, float)):

        proposed_number = _number(proposed_value)

        if proposed_number is not None:
            return proposed_number == float(constraint_value)

        return False


    if isinstance(constraint_value, str):

        if isinstance(proposed_value, str):
            return (
                proposed_value.strip().lower()
                == constraint_value.strip().lower()
            )

        return False
    if isinstance(constraint_value, dict):
        for deadline_key in ("must_return_by", "by", "deadline", "no_later_than", "before"):
            if deadline_key in constraint_value:
                deadline = _date(constraint_value[deadline_key])
                proposed_date = _date(proposed_value)
                if deadline is not None and proposed_date is not None:
                    return proposed_date <= deadline
                return False   # can't verify -> don't silently pass

        for start_key in ("must_start_by", "no_earlier_than", "after"):
            if start_key in constraint_value:
                earliest = _date(constraint_value[start_key])
                proposed_date = _date(proposed_value)
                if earliest is not None and proposed_date is not None:
                    return proposed_date >= earliest
                return False
    # --------------------------------------------------------
    # Structured equality
    # --------------------------------------------------------

    if isinstance(constraint_value, dict):

        # First try direct dictionary equality.
        if isinstance(proposed_value, dict):

            if proposed_value == constraint_value:
                return True

            # Compare common semantic numeric fields.
            for key in (
                "days",
                "duration_days",
                "hours",
                "weeks",
                "amount",
                "budget",
                "total",
                "price",
                "cost",
                "value",
                "max",
                "min",
            ):

                if (
                    key in constraint_value
                    and key in proposed_value
                ):

                    expected = _number(
                        constraint_value[key]
                    )

                    actual = _number(
                        proposed_value[key]
                    )

                    if (
                        expected is not None
                        and actual is not None
                    ):
                        return actual == expected

            return False

        # Allow a structured numeric constraint such as
        # {"days": 3} to match a simple proposal value of 3.
        expected_number = _number(constraint_value)
        proposed_number = _number(proposed_value)

        if (
            expected_number is not None
            and proposed_number is not None
        ):
            return proposed_number == expected_number

        return False

    # --------------------------------------------------------
    # Lists
    # --------------------------------------------------------

    if isinstance(constraint_value, list):

        if isinstance(proposed_value, list):
            return all(
                item in constraint_value
                for item in proposed_value
            )

        if isinstance(proposed_value, str):
            return proposed_value in constraint_value

        return False

    # --------------------------------------------------------
    # Unknown / unsupported HARD constraint
    # --------------------------------------------------------

    # A hard constraint that cannot be deterministically checked
    # must not be silently accepted.
    return False
def _find_related_term(
    terms: list[ProposalTerm],
    constraint: Constraint,
) -> Optional[ProposalTerm]:
    """
    Find the proposal term corresponding to a constraint.

    Uses exact/alias matching first, then semantic dimension
    matching for common negotiation categories.
    """

    # --------------------------------------------------------
    # Exact / existing alias match
    # --------------------------------------------------------

    term = _find_term(
        terms,
        constraint.key,
    )

    if term is not None:
        return term

    text = (
        f"{constraint.key} "
        f"{constraint.description}"
    ).lower()

    # --------------------------------------------------------
    # Budget / money / compensation
    # --------------------------------------------------------

    money_words = (
        "budget",
        "spend",
        "spending",
        "cost",
        "price",
        "amount",
        "salary",
        "compensation",
        "pay",
        "payment",
        "income",
        "wage",
        "lpa",
        "ctc",
        "package",
        "financial",
    )

    if any(word in text for word in money_words):

        for candidate in terms:

            candidate_key = _normalise_key(
                candidate.key
            )

            candidate_text = (
                f"{candidate_key} "
                f"{candidate.description}"
            ).lower()

            if any(
                word in candidate_text
                for word in money_words
            ):
                return candidate

    # --------------------------------------------------------
    # Duration / length
    # --------------------------------------------------------

    duration_words = (
        "trip",
        "duration",
        "length",
        "stay",
        "days",
        "weeks",
        "hours",
        "deadline",
        "timeline",
    )

    if any(word in text for word in duration_words):

        for candidate in terms:

            candidate_key = _normalise_key(
                candidate.key
            )

            candidate_text = (
                f"{candidate_key} "
                f"{candidate.description}"
            ).lower()

            if any(
                word in candidate_text
                for word in duration_words
            ):
                return candidate

    # --------------------------------------------------------
    # Date / start-date / joining-date
    # --------------------------------------------------------

    date_words = (
        "date",
        "start",
        "starting",
        "join",
        "joining",
        "deadline",
        "schedule",
        "day",
    )

    if any(word in text for word in date_words):

        for candidate in terms:

            candidate_key = _normalise_key(
                candidate.key
            )

            candidate_text = (
                f"{candidate_key} "
                f"{candidate.description}"
            ).lower()

            if any(
                word in candidate_text
                for word in date_words
            ):
                return candidate

    # --------------------------------------------------------
    # Accommodation / room
    # --------------------------------------------------------

    accommodation_words = (
        "room",
        "accommodation",
        "hostel",
        "hotel",
        "housing",
        "private",
        "shared",
    )

    if any(word in text for word in accommodation_words):

        for candidate in terms:

            candidate_key = _normalise_key(
                candidate.key
            )

            candidate_text = (
                f"{candidate_key} "
                f"{candidate.description}"
            ).lower()

            if any(
                word in candidate_text
                for word in accommodation_words
            ):
                return candidate

    return None
def validate_proposal_against_profile(
    proposal: Proposal,
    profile: ConstraintProfile,
) -> tuple[bool, Optional[str]]:
    """
    Check whether a proposal violates any HARD constraint
    belonging to the party making the proposal.
    """

    for constraint in profile.hard_constraints():

        term = _find_related_term(
            proposal.terms,
            constraint,
        )

        # If this proposal doesn't mention the hard constraint,
        # it can still discuss another dimension.
        if term is None:
            continue

        if not _satisfies_hard_constraint(
            constraint,
            term,
        ):
            return (
                False,
                f"Proposal violates hard constraint "
                f"'{constraint.key}' for "
                f"{profile.party_name}.",
            )

    return True, None


def validate_terms_against_profile(
    terms: list[ProposalTerm],
    profile: ConstraintProfile,
) -> tuple[bool, Optional[str]]:
    """
    Check whether a candidate final agreement satisfies ALL
    deterministic HARD constraints for one party.

    Unlike ordinary proposal validation, a FINAL agreement must
    contain enough information to validate every hard constraint.
    """

    for constraint in profile.hard_constraints():

        term = _find_related_term(
            terms,
            constraint,
        )

        # A final agreement must not silently omit a hard
        # constraint. If we cannot find the corresponding term,
        # we cannot prove the agreement satisfies it.
        if term is None:
            return (
                False,
                f"Final terms do not contain enough information "
                f"to verify hard constraint "
                f"'{constraint.key}' for "
                f"{profile.party_name}.",
            )

        if not _satisfies_hard_constraint(
            constraint,
            term,
        ):
            return (
                False,
                f"Final terms violate hard constraint "
                f"'{constraint.key}' for "
                f"{profile.party_name}.",
            )

    return True, None


def validate_final_terms(
    terms: list[ProposalTerm],
    profile_a: ConstraintProfile,
    profile_b: ConstraintProfile,
) -> tuple[bool, Optional[str]]:
    """
    Validate a candidate agreement against BOTH parties'
    HARD constraints.
    """

    valid_a, reason_a = validate_terms_against_profile(
        terms,
        profile_a,
    )

    if not valid_a:
        return False, reason_a

    valid_b, reason_b = validate_terms_against_profile(
        terms,
        profile_b,
    )

    if not valid_b:
        return False, reason_b

    return True, None


# ============================================================
# NEGOTIATION LOOP
# ============================================================

def run_negotiation(
    room_code: str,
    agent_a: BaseAgent,
    agent_b: BaseAgent,
    max_rounds: int = MAX_ROUNDS,
    force_accept_round: int = FORCE_ACCEPT_ROUND,
    on_round: Callable[[Proposal], None] = None,
) -> NegotiationTranscript:

    transcript = NegotiationTranscript(
        room_code=room_code,
        party_a=agent_a.profile.party_name,
        party_b=agent_b.profile.party_name,
    )

    speakers = [
        agent_a,
        agent_b,
    ]

    other_last: Proposal | None = None

    profiles = {
        "agent_a": agent_a.profile,
        "agent_b": agent_b.profile,
    }

    for round_number in range(
        1,
        max_rounds + 1,
    ):

        speaker = speakers[
            (round_number - 1) % 2
        ]

        proposal = speaker.next_move(
            round_number,
            other_last,
        )

        # ====================================================
        # STEP 1 — Validate the agent's own hard constraints
        # ====================================================

        proposal_valid, proposal_error = (
            validate_proposal_against_profile(
                proposal,
                speaker.profile,
            )
        )

        if not proposal_valid:

            transcript.stopped_reason = (
                "hard_constraint_conflict"
            )

            transcript.final_terms = []

            conflict_proposal = Proposal(
                round_number=round_number,
                speaker=proposal.speaker,
                action=proposal.action,
                terms=proposal.terms,
                rationale=(
                    "[REJECTED BY SAFETY CHECK] "
                    f"{proposal_error}"
                ),
                conceded_on=proposal.conceded_on,
            )

            transcript.proposals.append(
                conflict_proposal
            )

            if on_round:
                on_round(conflict_proposal)

            return transcript

        # ====================================================
        # STEP 2 — Validate ACCEPT
        # ====================================================

        if proposal.action == ProposalAction.ACCEPT:

            if other_last is None:

                transcript.stopped_reason = (
                    "hard_constraint_conflict"
                )

                transcript.final_terms = []

                if on_round:
                    on_round(proposal)

                transcript.proposals.append(
                    proposal
                )

                return transcript

            candidate_terms = other_last.terms

            valid_final, final_error = validate_final_terms(
                candidate_terms,
                agent_a.profile,
                agent_b.profile,
            )

            if not valid_final:

                conflict = Proposal(
                    round_number=round_number,
                    speaker=proposal.speaker,
                    action=proposal.action,
                    terms=proposal.terms,
                    rationale=(
                        "[NO FEASIBLE AGREEMENT] "
                        "The proposed final terms cannot satisfy "
                        "both parties' hard constraints. "
                        f"{final_error}"
                    ),
                    conceded_on=[],
                )

                transcript.proposals.append(conflict)

                if on_round:
                    on_round(conflict)

                transcript.stopped_reason = (
                    "hard_constraint_conflict"
                )

                transcript.final_terms = []

                return transcript

        # ====================================================
        # STEP 3 — Forced convergence safety check
        # ====================================================

        forced = False

        if (
            other_last is not None
            and round_number >= force_accept_round
            and proposal.action != ProposalAction.ACCEPT
        ):

            candidate_terms = other_last.terms

            valid_final, final_error = validate_final_terms(
                candidate_terms,
                agent_a.profile,
                agent_b.profile,
            )

            # ------------------------------------------------
            # CRITICAL:
            # Never force an invalid agreement.
            # ------------------------------------------------

            if not valid_final:

                conflict = Proposal(
                    round_number=round_number,
                    speaker=proposal.speaker,
                    action=proposal.action,
                    terms=proposal.terms,
                    rationale=(
                        "[NO FEASIBLE AGREEMENT] "
                        "Forced convergence was blocked because "
                        f"{final_error}"
                    ),
                    conceded_on=[],
                )

                transcript.proposals.append(
                    conflict
                )

                if on_round:
                    on_round(conflict)

                transcript.final_terms = []

                transcript.stopped_reason = (
                    "hard_constraint_conflict"
                )

                return transcript

            # ------------------------------------------------
            # Safe forced convergence
            # ------------------------------------------------

            proposal = Proposal(
                round_number=round_number,
                speaker=proposal.speaker,
                action=ProposalAction.ACCEPT,
                terms=other_last.terms,
                rationale=(
                    "(auto-converged — round cap reached) "
                    f"{proposal.rationale}"
                ),
                conceded_on=[],
            )

            forced = True

        # ====================================================
        # STEP 4 — Record proposal
        # ====================================================

        transcript.proposals.append(
            proposal
        )

        if on_round:
            on_round(proposal)

        # ====================================================
        # STEP 5 — Finish on ACCEPT
        # ====================================================

        if proposal.action == ProposalAction.ACCEPT:

            candidate_terms = (
                other_last.terms
                if other_last is not None
                else proposal.terms
            )

            # Final safety check AGAIN immediately before
            # committing the agreement.
            valid_final, final_error = validate_final_terms(
                candidate_terms,
                agent_a.profile,
                agent_b.profile,
            )

            if not valid_final:

                transcript.final_terms = []

                transcript.stopped_reason = (
                    "hard_constraint_conflict"
                )

                return transcript

            transcript.final_terms = candidate_terms

            transcript.stopped_reason = (
                "forced_convergence"
                if forced
                else "mutual_accept"
            )

            return transcript

        # Current proposal becomes the other side's next offer.
        other_last = proposal

    # ========================================================
    # MAX ROUND FALLBACK
    # ========================================================

    if other_last is not None:

        valid_final, final_error = validate_final_terms(
            other_last.terms,
            agent_a.profile,
            agent_b.profile,
        )

        if valid_final:

            transcript.final_terms = (
                other_last.terms
            )

            transcript.stopped_reason = (
                "max_rounds"
            )

        else:

            transcript.final_terms = []

            transcript.stopped_reason = (
                "hard_constraint_conflict"
            )

    else:

        transcript.final_terms = []

        transcript.stopped_reason = (
            "max_rounds"
        )

    return transcript