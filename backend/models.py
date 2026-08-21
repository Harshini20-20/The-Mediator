"""
API-level request/response models. Kept separate from mediator/schema.py —
that module is the engine's internal data model; this one is the HTTP
contract. They overlap (both reference ConstraintProfile) but evolving the
API shape shouldn't force changes to the engine's core types, and vice versa.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from mediator.schema import ConstraintProfile, Proposal, FairnessVerdict


class RoomStatus(str, Enum):
    WAITING_FOR_B = "waiting_for_b"          # room created, second party hasn't joined
    COLLECTING_CONSTRAINTS = "collecting_constraints"  # both joined, waiting on one/both profiles
    NEGOTIATING = "negotiating"               # background negotiation in progress
    DONE = "done"                              # negotiation finished, result available
    ERROR = "error"                            # something went wrong (e.g. API failure)


class CreateRoomRequest(BaseModel):
    party_a_name: str


class CreateRoomResponse(BaseModel):
    room_code: str
    role: str = "a"


class JoinRoomRequest(BaseModel):
    party_b_name: str


class JoinRoomResponse(BaseModel):
    room_code: str
    role: str = "b"
    party_a_name: str


class SubmitConstraintsRequest(BaseModel):
    role: str  # "a" | "b"
    profile: ConstraintProfile


class ExtractConstraintsRequest(BaseModel):
    role: str  # "a" | "b"
    party_name: str
    free_text: str  # raw intake chat — "I need the trip under 25k, dates are flexible..."


class RoomStatusResponse(BaseModel):
    room_code: str
    status: RoomStatus
    party_a_name: Optional[str] = None
    party_b_name: Optional[str] = None
    party_a_submitted: bool = False
    party_b_submitted: bool = False
    rounds_so_far: list[Proposal] = []
    error_message: Optional[str] = None


class RoomResultResponse(BaseModel):
    room_code: str
    status: RoomStatus
    stopped_reason: Optional[str] = None
    final_terms: list = []
    all_proposals: list[Proposal] = []
    verdict: Optional[FairnessVerdict] = None
