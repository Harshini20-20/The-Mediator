"""
FastAPI app — wraps mediator/negotiation.py and mediator/fairness.py behind
HTTP endpoints with room-code pairing.

Run it:
    uvicorn backend.app:app --reload --port 8000

Flow:
    1. POST /api/rooms                        — party A creates a room, gets a room_code
    2. POST /api/rooms/{code}/join             — party B joins with the code
    3. POST /api/rooms/{code}/extract          — (optional) turn free-text into a ConstraintProfile
    4. POST /api/rooms/{code}/constraints      — each party submits their (private) profile
       -> once BOTH are in, negotiation kicks off automatically in a background thread
    5. GET  /api/rooms/{code}/status           — poll for live status + rounds so far
    6. GET  /api/rooms/{code}/result           — final terms + fairness verdict, once done

Each party only ever sees their OWN profile and the shared negotiation
transcript — never the other party's raw constraints. That separation is
enforced simply by never returning profile_a/profile_b in any response.
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from mediator.agents import make_agent
from mediator.fairness import check_fairness
from mediator.negotiation import run_negotiation
from mediator.schema import Proposal

from .intake import extract_constraints
from .models import (
    CreateRoomRequest, CreateRoomResponse,
    JoinRoomRequest, JoinRoomResponse,
    SubmitConstraintsRequest, ExtractConstraintsRequest,
    RoomStatusResponse, RoomResultResponse, RoomStatus,
)
from .store import store

app = FastAPI(title="Mediator API", version="0.1.0")

# Set MEDIATOR_MOCK=1 to run every negotiation through the deterministic
# mock agents instead of a real LLM provider — mirrors the CLI's --mock
# flag. Useful for testing the room-pairing/threading/status-polling flow
# without burning API calls, and for testing without any key at all.
MOCK_MODE = os.environ.get("MEDIATOR_MOCK", "0") == "1"

# Wide open for hackathon dev — tighten this to your actual frontend origin
# before a public demo if it matters for your setup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/rooms", response_model=CreateRoomResponse)
def create_room(req: CreateRoomRequest):
    room = store.create(party_a_name=req.party_a_name)
    return CreateRoomResponse(room_code=room.room_code, role="a")


@app.post("/api/rooms/{room_code}/join", response_model=JoinRoomResponse)
def join_room(room_code: str, req: JoinRoomRequest):
    room = store.get(room_code)
    if room is None:
        raise HTTPException(404, "Room not found — check the code")
    if room.party_b_name is not None:
        raise HTTPException(409, "This room already has two parties")
    room = store.join(room_code, party_b_name=req.party_b_name)
    return JoinRoomResponse(room_code=room.room_code, role="b", party_a_name=room.party_a_name)


@app.post("/api/rooms/{room_code}/extract")
def extract(room_code: str, req: ExtractConstraintsRequest):
    room = store.get(room_code)
    if room is None:
        raise HTTPException(404, "Room not found")
    try:
        profile = extract_constraints(req.party_name, req.free_text, mock=MOCK_MODE)
    except Exception as e:
        raise HTTPException(502, f"Constraint extraction failed: {e}")
    return profile.model_dump()


@app.post("/api/rooms/{room_code}/constraints")
def submit_constraints(room_code: str, req: SubmitConstraintsRequest):
    if req.role not in ("a", "b"):
        raise HTTPException(400, "role must be 'a' or 'b'")

    room = store.get(room_code)
    if room is None:
        raise HTTPException(404, "Room not found")

    room = store.submit_profile(room_code, req.role, req.profile)

    if room.profile_a is not None and room.profile_b is not None and room.status != RoomStatus.NEGOTIATING:
        store.mark_negotiating(room_code)
        thread = threading.Thread(target=_run_negotiation_job, args=(room_code,), daemon=True)
        thread.start()

    return {"ok": True, "both_submitted": room.profile_a is not None and room.profile_b is not None}


@app.get("/api/rooms/{room_code}/status", response_model=RoomStatusResponse)
def get_status(room_code: str):
    room = store.get(room_code)
    if room is None:
        raise HTTPException(404, "Room not found")
    print(
        "STATUS DEBUG:",
        room.room_code,
        room.status,
        "A=", room.profile_a is not None,
        "B=", room.profile_b is not None,
    )
    return RoomStatusResponse(
        room_code=room.room_code,
        status=room.status,
        party_a_name=room.party_a_name,
        party_b_name=room.party_b_name,
        party_a_submitted=room.profile_a is not None,
        party_b_submitted=room.profile_b is not None,
        rounds_so_far=room.proposals,
        error_message=room.error_message,
    )


@app.get("/api/rooms/{room_code}/result", response_model=RoomResultResponse)
def get_result(room_code: str):
    room = store.get(room_code)
    if room is None:
        raise HTTPException(404, "Room not found")
    if room.status != RoomStatus.DONE:
        raise HTTPException(409, f"Negotiation not finished yet (status={room.status.value})")
    return RoomResultResponse(
        room_code=room.room_code,
        status=room.status,
        stopped_reason=room.stopped_reason,
        final_terms=room.final_terms,
        all_proposals=room.proposals,
        verdict=room.verdict,
    )


def _run_negotiation_job(room_code: str) -> None:
    """
    Runs in a background thread once both profiles are in. Uses the
    on_round callback to push each proposal into the room store live, so
    /status reflects progress as it happens rather than only at the end.
    """
    room = store.get(room_code)
    if room is None:
        return

    try:
        agent_a = make_agent(room.profile_a, "agent_a", mock=MOCK_MODE)
        agent_b = make_agent(room.profile_b, "agent_b", mock=MOCK_MODE)

        def on_round(proposal: Proposal):
            store.append_proposal(room_code, proposal)

        transcript = run_negotiation(
            room_code=room_code,
            agent_a=agent_a,
            agent_b=agent_b,
            on_round=on_round,
        )

        verdict = check_fairness(transcript, room.profile_a, room.profile_b, mock=MOCK_MODE)

        store.mark_done(
            room_code,
            stopped_reason=transcript.stopped_reason,
            final_terms=[t.model_dump() for t in (transcript.final_terms or [])],
            verdict=verdict,
        )
    except Exception as e:
        store.mark_error(room_code, str(e))


@app.get("/")
def health():
    return {"status": "ok", "service": "mediator-api"}
