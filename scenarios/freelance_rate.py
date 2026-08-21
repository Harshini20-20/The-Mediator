"""Scenario: a freelancer and a client negotiating scope and rate."""

from mediator.schema import ConstraintProfile, Constraint, ConstraintType

PARTY_A = ConstraintProfile(
    party_name="Freelancer (Ananya)",
    scenario_summary="Needs a minimum day rate but is flexible on project scope",
    constraints=[
        Constraint(
            key="day_rate",
            description="Cannot go below 6,000 INR per day — this is her floor",
            type=ConstraintType.HARD,
            value={"currency": "INR", "min": 6000},
        ),
        Constraint(
            key="revision_rounds",
            description="Prefers to cap revisions at 2 rounds",
            type=ConstraintType.SOFT,
            priority=3,
            value={"preferred_max": 2},
        ),
        Constraint(
            key="payment_terms",
            description="Would like 50% upfront",
            type=ConstraintType.SOFT,
            priority=4,
        ),
        Constraint(
            key="timeline",
            description="Prefers a 3-week timeline over 2",
            type=ConstraintType.SOFT,
            priority=2,
        ),
    ],
)

PARTY_B = ConstraintProfile(
    party_name="Client (Studio Nine)",
    scenario_summary="Has a fixed total budget but needs the work done fast",
    constraints=[
        Constraint(
            key="total_budget",
            description="Total project budget is capped at 60,000 INR — cannot be exceeded",
            type=ConstraintType.HARD,
            value={"currency": "INR", "max": 60000},
        ),
        Constraint(
            key="timeline",
            description="Would strongly prefer a 2-week turnaround",
            type=ConstraintType.SOFT,
            priority=4,
        ),
        Constraint(
            key="revision_rounds",
            description="Wants at least 3 revision rounds included",
            type=ConstraintType.SOFT,
            priority=3,
        ),
        Constraint(
            key="payment_terms",
            description="Prefers 25% upfront, rest on delivery",
            type=ConstraintType.SOFT,
            priority=2,
        ),
    ],
)
