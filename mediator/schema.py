"""
Core data model for the Mediator negotiation engine.

Design principles:
- Every user's position is split into HARD constraints (non-negotiable),
  SOFT preferences (negotiable, ranked), and a priority order between them.
- A negotiation is a bounded sequence of rounds. Each round is one
  proposal from one agent. The loop stops when either both agents accept
  the same proposal, or MAX_ROUNDS is hit.
- Nothing about User A's raw constraints is ever shown to Agent B, and
  vice versa — only what each agent chooses to reveal via a Proposal.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field


class ConstraintType(str, Enum):
    HARD = "hard"       # non-negotiable
    SOFT = "soft"       # negotiable, ranked by priority


class Constraint(BaseModel):
    """One line item in a user's private brief."""

    key: str = Field(
        ...,
        description="Short machine-friendly identifier, e.g. 'budget_cap'"
    )

    description: str = Field(
        ...,
        description="Human-readable statement of this constraint"
    )

    type: ConstraintType

    # For SOFT constraints: 1 (low) to 5 (high).
    # Ignored for HARD constraints.
    priority: int = Field(
        default=3,
        ge=1,
        le=5
    )

    # Accept structured objects OR simple values.
    #
    # Examples:
    # {"max": 25000}
    # {"min_days": 5}
    # "private room"
    # 5
    # 25000
    value: Optional[Union[dict, list, str, int, float]] = None


class ConstraintProfile(BaseModel):
    """The full private brief for one party."""

    party_name: str

    scenario_summary: str = Field(
        ...,
        description="One-line summary of what this party wants"
    )

    constraints: list[Constraint]

    def hard_constraints(self) -> list[Constraint]:
        return [
            c for c in self.constraints
            if c.type == ConstraintType.HARD
        ]

    def soft_constraints(self) -> list[Constraint]:
        return sorted(
            (
                c for c in self.constraints
                if c.type == ConstraintType.SOFT
            ),
            key=lambda c: c.priority,
            reverse=True,
        )


class ProposalTerm(BaseModel):
    """One term inside a proposal."""

    key: str
    description: str

    # Accepts:
    # {"days": 5}
    # "private room"
    # 5
    # 25000
    value: Optional[Union[dict, list, str, int, float]] = None


class ProposalAction(str, Enum):
    PROPOSE = "propose"
    ACCEPT = "accept"
    CONCEDE = "concede"


class Proposal(BaseModel):
    """A single move in the negotiation."""

    round_number: int
    speaker: str  # "agent_a" | "agent_b"

    action: ProposalAction

    terms: list[ProposalTerm]

    rationale: str = Field(
        ...,
        description="Short, human-readable reasoning for this move"
    )

    conceded_on: list[str] = Field(
        default_factory=list,
        description="Keys this speaker gave ground on"
    )


class NegotiationTranscript(BaseModel):
    """Full record of a negotiation session."""

    room_code: str

    party_a: str
    party_b: str

    proposals: list[Proposal] = Field(
        default_factory=list
    )

    final_terms: Optional[list[ProposalTerm]] = None

    stopped_reason: Optional[str] = None
    # Possible values:
    # "mutual_accept"
    # "forced_convergence"
    # "max_rounds"
    # "hard_constraint_conflict"

    def last_proposal(self) -> Optional[Proposal]:
        return self.proposals[-1] if self.proposals else None
class FairnessVerdict(BaseModel):
    """Output of the independent fairness-check layer."""

    is_balanced: bool

    balance_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="0=fully one-sided,100=perfectly balanced"
    )

    explanation_for_a: str = Field(
        ...,
        description="Neutral summary of what A gave up / gained"
    )

    explanation_for_b: str = Field(
        ...,
        description="Neutral summary of what B gave up / gained"
    )