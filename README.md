# The Mediator

## Private AI agents negotiating on your behalf

The Mediator is a multi-agent AI negotiation platform designed to help two parties reach an agreement without exposing their private requirements to each other.

Instead of giving one AI access to both sides' information, The Mediator gives each party an independent AI agent. Each agent knows only its own constraints and preferences and negotiates through structured proposals.

A deterministic safety layer ensures that non-negotiable requirements are never violated, while an independent fairness layer evaluates the final outcome and explains what each party gained and gave up.

The goal is simple:

**Let AI negotiate. Keep private information private. Never compromise on what cannot be compromised.**

---

## Why The Mediator?

Imagine two people negotiating a trip, salary, freelance contract, purchase, or any other decision.

One person may privately have a maximum budget of ₹60,000.

The other may privately refuse anything below ₹90,000.

A conventional AI negotiator could see both numbers and calculate a compromise.

But that is not how a real private negotiation should work.

The Mediator keeps those positions isolated.

Each agent negotiates using only what its party has revealed and what the other side explicitly puts into a proposal.

---

## How It Works

```text
Party A                         Party B
   |                               |
Private constraints           Private constraints
   |                               |
   v                               v
Agent A                         Agent B
   |                               |
   +-------- Structured Proposals--+
                    |
                    v
          Negotiation Engine
                    |
                    v
       Deterministic Validation
                    |
          +---------+---------+
          |                   |
        Valid               Invalid
          |                   |
          v                   v
      Continue              Reject
          |
          v
    Final Agreement
          |
          v
 Independent Fairness Check
          |
          v
 Agreement / No Agreement