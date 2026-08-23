# The Mediator

## Private AI agents negotiating on your behalf

The Mediator is a multi-agent AI negotiation platform designed to help two parties reach an agreement without exposing their private requirements to each other.

Instead of giving one AI access to both sides' information, The Mediator gives each party an independent AI agent. Each agent knows only its own constraints and preferences and negotiates through structured proposals.

A deterministic safety layer ensures that non-negotiable requirements are never violated, while an independent fairness layer evaluates the final outcome and explains what each party gained and gave up.

The goal is simple:

**Let AI negotiate. Keep private information private. Never compromise on what cannot be compromised.**

---

# Why The Mediator?

Imagine two people negotiating a trip, salary, freelance contract, purchase, or any other decision.

One person may privately have a maximum budget of ₹60,000.

The other may privately refuse anything below ₹90,000.

A conventional AI negotiator could see both sides' requirements and calculate a compromise.

But that gives the negotiator information that neither party necessarily intended to reveal.

The Mediator takes a different approach.

Each party is represented by an independent AI agent. The agents negotiate using their own private requirements and only see information explicitly revealed through the negotiation.

This turns negotiation from a single-model problem into a controlled multi-agent system.

---

# Core Features

## Private Agent Architecture

Each party is represented by an independent AI agent.

An agent receives:

- Its party's hard constraints
- Its party's soft preferences
- Its priorities
- Information explicitly revealed during negotiation

Agents do not receive:

- The other party's raw intake
- The other party's private constraint profile
- The other party's private rationale

Privacy is enforced through the application's information flow rather than relying only on the model to keep information private.

---

## Constraint-Aware Negotiation

Requirements are divided into two categories.

### Hard Constraints

Non-negotiable requirements that must never be violated.

### Soft Preferences

Negotiable preferences that agents can concede to reach an agreement.

The AI handles the negotiation, while deterministic Python validation ensures that hard constraints are respected.

**AI decides how to negotiate. The system decides what cannot be violated.**

---

## Independent Fairness Evaluation

After negotiation, a separate fairness layer evaluates the outcome.

It produces:

- A fairness score
- What each party gained
- What each party gave up
- An explanation of the final outcome

The fairness evaluation is performed independently from the negotiating agents.

---

## No-Agreement Handling

The Mediator does not force an agreement when the parties' hard constraints are incompatible.

If no valid solution exists, the system clearly returns a **No Agreement** result instead of producing an invalid compromise.

**A failed negotiation is better than an invalid agreement.**

---

# How It Works

'''text
             PARTY A                         PARTY B
                |                               |
        Private requirements             Private requirements
                |                               |
                v                               v
          +-----------+                   +-----------+
          |  Agent A  |                   |  Agent B  |
          +-----+-----+                   +-----+-----+
                |                               |
                +------ Structured Proposals ---+
                               |
                               v
                    Negotiation Engine
                               |
                               v
                 Hard Constraint Validator
                               |
                    +----------+----------+
                    |                     |
                  Valid                 Invalid
                    |                     |
                    v                     v
                Continue               Reject
                    |
                    v
             Final Agreement
                    |
                    v
          Independent Fairness Check
                    |
                    v
            Agreement / No Agreement
            
'''
# Try It Now
The fastest way to see The Mediator work is Mock Mode — the full negotiation flow,
running end to end, with no API key and no external calls.

```bash
git clone https://github.com/Harshini20-20/The-Mediator.git
cd The-Mediator

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:MEDIATOR_MOCK="1"
python -m uvicorn backend.app:app --reload --port 8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints. Create a room. Run a negotiation.

Nothing here calls an external API. This is the whole product, working, in under a
minute.

---

# Running It Live

Mock Mode proves the architecture. Live Mode proves the AI.

Live negotiations run on [Groq](https://console.groq.com), which offers a free tier
with no card required.

1. Get a key at console.groq.com.
2. Create a `.env` file in the project root:

```env
MEDIATOR_PROVIDER=groq
GROQ_API_KEY=your_key_here
```

3. Start the backend without `MEDIATOR_MOCK` set:

```bash
python -m uvicorn backend.app:app --reload --port 8000
```

4. Start the frontend the same way as above.

No key belongs in this repository. `.env` is git-ignored. Anyone running this project
brings their own key.

---

# Tech Stack

**Backend** — Python, FastAPI, Pydantic.

**Frontend** — React, Vite, Tailwind CSS.

**Negotiation engine** — a custom round-based state machine. Hard constraints are
enforced by deterministic code, never left to a model's judgment.

**Rooms** — short alphanumeric codes. No accounts, no signup.

**State** — in-memory for this build. Swappable for Redis or Postgres for anything
beyond a demo.

---

# Project Structure

```text
The-Mediator/
├── mediator/          core negotiation engine
│   ├── schema.py        the data model
│   ├── agents.py         negotiating agents — Groq, Anthropic, or mock
│   ├── negotiation.py     the round loop and hard-constraint validator
│   └── fairness.py        the independent fairness layer
├── backend/           FastAPI, room-code pairing
├── frontend/          the React app
├── scenarios/         example negotiations for CLI testing
├── main.py            CLI runner
└── .env.example
```

---

# API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/rooms` | Create a room |
| POST | `/api/rooms/{code}/join` | Join a room |
| POST | `/api/rooms/{code}/extract` | Turn free text into structured constraints |
| POST | `/api/rooms/{code}/constraints` | Submit a party's profile |
| GET | `/api/rooms/{code}/status` | Poll live negotiation status |
| GET | `/api/rooms/{code}/result` | Final terms and fairness verdict |

Submitting constraints for both parties starts the negotiation automatically. Nothing
else needs to be triggered by hand.

---

# Hackathon Context

Built for Prasunethon 2.0 — Artificial Intelligence & Machine Learning track.


