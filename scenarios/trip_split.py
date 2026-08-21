"""Scenario: two friends planning a trip together, splitting cost and dates."""

from mediator.schema import ConstraintProfile, Constraint, ConstraintType

PARTY_A = ConstraintProfile(
    party_name="Riya",
    scenario_summary="Wants a budget-friendly trip but is flexible on dates",
    constraints=[
        Constraint(
            key="budget_cap",
            description="Total trip cost must not exceed 25,000 INR",
            type=ConstraintType.HARD,
            value={"currency": "INR", "max": 25000},
        ),
        Constraint(
            key="travel_dates",
            description="Prefers early December but can shift by a week either way",
            type=ConstraintType.SOFT,
            priority=2,
            value={"preferred": "2026-12-05"},
        ),
        Constraint(
            key="accommodation_type",
            description="Would like a private room, not a hostel dorm",
            type=ConstraintType.SOFT,
            priority=4,
        ),
        Constraint(
            key="trip_length",
            description="Wants at least 5 days",
            type=ConstraintType.SOFT,
            priority=3,
            value={"min_days": 5},
        ),
    ],
)

PARTY_B = ConstraintProfile(
    party_name="Karan",
    scenario_summary="Has a fixed work trip right after, so dates are locked, budget flexible",
    constraints=[
        Constraint(
            key="travel_dates",
            description="Must be back by December 12 for a work commitment — dates are fixed",
            type=ConstraintType.HARD,
            value={"must_return_by": "2026-12-12"},
        ),
        Constraint(
            key="budget_cap",
            description="Comfortable up to 35,000 INR, would prefer to spend less",
            type=ConstraintType.SOFT,
            priority=2,
            value={"currency": "INR", "max": 35000},
        ),
        Constraint(
            key="accommodation_type",
            description="Fine with a hostel dorm to save money",
            type=ConstraintType.SOFT,
            priority=1,
        ),
        Constraint(
            key="trip_length",
            description="Would prefer a shorter 3-4 day trip",
            type=ConstraintType.SOFT,
            priority=3,
            value={"max_days": 4},
        ),
    ],
)
