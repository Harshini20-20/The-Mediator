# Mediator — Negotiation Engine

The core, judged-on-innovation piece of the Mediator project: two AI agents privately
represent two parties, negotiate directly with each other, and converge on a compromise —
checked for fairness by an independent third AI role.

This is a standalone engine with **no backend or frontend dependency** — you can run it
from the terminal right now and see the whole negotiation happen.

## Setup (VS Code)

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Pick ONE provider for live runs (mock mode needs neither):

# Option A — Groq (free tier, no card needed)
export MEDIATOR_PROVIDER=groq
export GROQ_API_KEY=gsk_...

# Option B — Anthropic (paid API, $5 signup credit if issued to your account)
export MEDIATOR_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

`MEDIATOR_PROVIDER` defaults to `groq` if unset. Both providers use the exact same
negotiation logic, schema, and prompts — only the API call underneath changes. You can
switch providers any time without touching `mediator/negotiation.py` or `mediator/schema.py`.

## Run it

```bash
# Offline — no API key needed. Validates the negotiation LOOP LOGIC
# (round counting, stopping conditions, concession flow) using deterministic
# mock agents. Do this first, always.
python main.py trip_split --mock
python main.py freelance_rate --mock

# Live — calls the real Claude API for actual negotiation reasoning.
python main.py trip_split
python main.py freelance_rate
```

## How it's structured

```
mediator/
  schema.py       — the data model: ConstraintProfile, Proposal, NegotiationTranscript, FairnessVerdict
  agents.py        — LiveAgent (real API) + MockAgent (offline testing) behind one interface
  negotiation.py   — the round-by-round state machine / stopping conditions
  fairness.py      — the independent third-role fairness check + plain-language explanation

scenarios/
  trip_split.py     — two friends, one hard-constrained on dates, one on budget
  freelance_rate.py — freelancer vs client, day-rate vs total-budget conflict

main.py            — CLI runner that wires it all together and prints the full transcript
```

## Design decisions worth knowing before you extend this

- **Constraints are split into HARD (never violated) and SOFT (ranked 1–5).**
  Only SOFT items get conceded during negotiation. This is what stops an agent from ever
  agreeing to something that breaks its principal's real limit.
- **Agents never see each other's raw constraints** — only what's revealed through a
  `Proposal`. The fairness layer is the only role that sees both full profiles, which is
  what makes its "what you didn't know" explanation meaningful rather than something
  either agent could have said itself.
- **Max 8 rounds.** The system prompt tells agents they must converge by round 5+. If
  round 8 hits with no acceptance, the loop stops with `stopped_reason="max_rounds"` —
  wire this to a "no clean agreement, here's the closest offer" screen rather than an
  error state.
- **`--mock` mode is not a toy** — it's how you validate the loop's control flow (does it
  terminate? does round counting work? does accept end things correctly?) without spending
  API calls or waiting on a key. Keep it working as you extend the engine; it'll save you
  time all 24 hours, especially when you wire this into FastAPI next and want to test the
  endpoints without hitting the real API every time.

## Next steps (Phase 3 in the roadmap)

1. ~~Wrap `run_negotiation()` in a FastAPI endpoint~~ — done, see `backend/`.
2. ~~Add a private intake step~~ — done, see `backend/intake.py`.
3. Build the React frontend against the endpoints below.

---

## Backend (FastAPI + room-code pairing)

```bash
# from the mediator-engine/ root, with your venv active and requirements installed:
export MEDIATOR_PROVIDER=groq
export GROQ_API_KEY=gsk_...
uvicorn backend.app:app --reload --port 8000
```

Or test the whole flow with zero API calls first:
```bash
export MEDIATOR_MOCK=1
uvicorn backend.app:app --reload --port 8000
```

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/rooms` | Party A creates a room. Body: `{"party_a_name": "Riya"}`. Returns `room_code`. |
| POST | `/api/rooms/{code}/join` | Party B joins. Body: `{"party_b_name": "Karan"}`. |
| POST | `/api/rooms/{code}/extract` | (optional) Turn free text into a `ConstraintProfile` via LLM. Body: `{"role": "a", "party_name": "Riya", "free_text": "..."}`. |
| POST | `/api/rooms/{code}/constraints` | Submit a party's profile. Body: `{"role": "a", "profile": {...}}`. Once BOTH are submitted, negotiation starts automatically in the background. |
| GET | `/api/rooms/{code}/status` | Poll live status + rounds so far — this is what your "Agent A proposing..." UI polls. |
| GET | `/api/rooms/{code}/result` | Final terms + fairness verdict. 409 until status is `done`. |

### Design notes

- **Room-code pairing** — `store.py` generates a 6-character code (e.g. `K3F9QZ`), no accounts needed. This is a single in-memory process store; fine for a hackathon demo, but restarting the server wipes all rooms. Swap for Redis/Postgres if you need persistence.
- **Negotiation runs in a background thread**, kicked off automatically the moment both profiles are in — the client that submits second gets `both_submitted: true` in the response, and everyone should start polling `/status` from there.
- **Neither party's raw profile is ever returned** by any endpoint — only the shared transcript and final verdict. This is the actual privacy guarantee the whole product depends on; don't add a route that echoes back `profile_a`/`profile_b`.
- **`MEDIATOR_MOCK=1`** mirrors the CLI's `--mock` flag — runs the entire room lifecycle (including a mock constraint extractor) with zero API calls. Use this to test your frontend's polling/status logic without burning credits.

## Model

Default model per provider:
- `groq`: `llama-3.3-70b-versatile`
- `anthropic`: `claude-sonnet-5`

Override with `MEDIATOR_MODEL=<model-string>` if you want to experiment — e.g.
`MEDIATOR_MODEL=llama-3.1-8b-instant` for faster/cheaper Groq testing, or
`MEDIATOR_MODEL=claude-opus-4-8` for higher-quality Anthropic runs.
