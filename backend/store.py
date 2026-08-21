"""
In-memory room store — deliberately NOT a database yet.

For a 24h hackathon MVP this is the right call: it's zero-setup, and the
roadmap already earmarks PostgreSQL/Firebase as the Phase-3+ upgrade once
you need rooms to survive a server restart or scale past one process.
Swapping this out later means implementing the same four methods
(create, get, join, update) against a real DB — nothing above this layer
needs to change.

Thread safety matters here because negotiations run in a background
thread (see app.py) while the main request thread keeps polling/reading —
a plain dict without a lock can corrupt under that access pattern.
"""

from __future__ import annotations

import random
import string
import threading
from dataclasses import dataclass, field
from typing import Optional

from mediator.schema import ConstraintProfile, FairnessVerdict, Proposal

from .models import RoomStatus


@dataclass
class Room:
    room_code: str
    party_a_name: str
    party_b_name: Optional[str] = None
    profile_a: Optional[ConstraintProfile] = None
    profile_b: Optional[ConstraintProfile] = None
    status: RoomStatus = RoomStatus.WAITING_FOR_B
    proposals: list[Proposal] = field(default_factory=list)
    stopped_reason: Optional[str] = None
    final_terms: list = field(default_factory=list)
    verdict: Optional[FairnessVerdict] = None
    error_message: Optional[str] = None


class RoomStore:
    def __init__(self):
        self._rooms: dict[str, Room] = {}
        self._lock = threading.Lock()

    def _generate_code(self) -> str:
        # 6 uppercase alphanumeric chars, e.g. "K3F9QZ" — short enough to
        # read aloud to a friend, long enough to not collide in a demo.
        alphabet = string.ascii_uppercase + string.digits
        while True:
            code = "".join(random.choices(alphabet, k=6))
            if code not in self._rooms:
                return code

    def create(self, party_a_name: str) -> Room:
        with self._lock:
            code = self._generate_code()
            room = Room(room_code=code, party_a_name=party_a_name)
            self._rooms[code] = room
            return room

    def get(self, room_code: str) -> Optional[Room]:
        with self._lock:
            return self._rooms.get(room_code.upper())

    def join(self, room_code: str, party_b_name: str) -> Optional[Room]:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room is None:
                return None
            room.party_b_name = party_b_name
            room.status = RoomStatus.COLLECTING_CONSTRAINTS
            return room

    def submit_profile(self, room_code: str, role: str, profile: ConstraintProfile) -> Optional[Room]:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room is None:
                return None
            if role == "a":
                room.profile_a = profile
            elif role == "b":
                room.profile_b = profile
            return room

    def append_proposal(self, room_code: str, proposal: Proposal) -> None:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room:
                room.proposals.append(proposal)

    def mark_negotiating(self, room_code: str) -> None:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room:
                room.status = RoomStatus.NEGOTIATING

    def mark_done(self, room_code: str, stopped_reason: str, final_terms: list, verdict: FairnessVerdict) -> None:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room:
                room.stopped_reason = stopped_reason
                room.final_terms = final_terms
                room.verdict = verdict
                room.status = RoomStatus.DONE

    def mark_error(self, room_code: str, message: str) -> None:
        with self._lock:
            room = self._rooms.get(room_code.upper())
            if room:
                room.error_message = message
                room.status = RoomStatus.ERROR


# Single process-wide store. Fine for a hackathon single-instance deploy;
# would need a shared backend (Redis, DB) the moment you run >1 server process.
store = RoomStore()
