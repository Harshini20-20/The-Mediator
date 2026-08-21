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

1. Wrap `run_negotiation()` in a FastAPI endpoint — call `on_round` to push live status
   over a websocket or polled endpoint so the frontend can show "Agent A proposing...".
2. Add a private intake step that turns free-form chat into a `ConstraintProfile` via a
   structured-output API call (same `tool_choice` pattern used in `agents.py`).
3. Wire `FairnessVerdict` into the reveal screen — `what_a_didnt_know` /
   `what_b_didnt_know` are written to be shown directly as the "payoff" moment.

## Model

Default model per provider:
- `groq`: `llama-3.3-70b-versatile`
- `anthropic`: `claude-sonnet-5`

Override with `MEDIATOR_MODEL=<model-string>` if you want to experiment — e.g.
`MEDIATOR_MODEL=llama-3.1-8b-instant` for faster/cheaper Groq testing, or
`MEDIATOR_MODEL=claude-opus-4-8` for higher-quality Anthropic runs.
