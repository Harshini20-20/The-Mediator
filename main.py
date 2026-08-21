"""
CLI runner — proves the negotiation engine end-to-end from the terminal,
no backend or frontend required yet.

Usage:
    python main.py trip_split --mock        # test loop logic offline, no API key needed
    python main.py trip_split                # run for real against the Claude API
    python main.py freelance_rate --mock
"""

import argparse
import importlib
import sys

from mediator.agents import make_agent, PROVIDER, MODEL
from mediator.fairness import check_fairness
from mediator.negotiation import run_negotiation
from mediator.schema import ProposalAction


def print_proposal(p):
    icon = {"propose": "→", "accept": "✓", "concede": "↳"}[p.action.value]
    print(f"\n  Round {p.round_number} [{p.speaker}] {icon} {p.action.value.upper()}")
    print(f"    {p.rationale}")
    if p.conceded_on:
        print(f"    conceded on: {', '.join(p.conceded_on)}")
    for t in p.terms:
        print(f"      - {t.key}: {t.description}")


def main():
    parser = argparse.ArgumentParser(description="Run a Mediator negotiation scenario end-to-end.")
    parser.add_argument("scenario", help="scenario module name under scenarios/, e.g. trip_split")
    parser.add_argument("--mock", action="store_true", help="use deterministic mock agents — no API key needed")
    args = parser.parse_args()

    try:
        scenario = importlib.import_module(f"scenarios.{args.scenario}")
    except ModuleNotFoundError:
        print(f"No scenario named '{args.scenario}' found under scenarios/", file=sys.stderr)
        sys.exit(1)

    profile_a, profile_b = scenario.PARTY_A, scenario.PARTY_B

    print("=" * 70)
    print(f"MEDIATOR — negotiating: {profile_a.party_name} vs {profile_b.party_name}")
    mode_label = "MOCK (offline)" if args.mock else f"LIVE ({PROVIDER} / {MODEL})"
    print(f"mode: {mode_label}")
    print("=" * 70)

    agent_a = make_agent(profile_a, "agent_a", mock=args.mock)
    agent_b = make_agent(profile_b, "agent_b", mock=args.mock)

    transcript = run_negotiation(
        room_code="DEMO01",
        agent_a=agent_a,
        agent_b=agent_b,
        on_round=print_proposal,
    )

    print("\n" + "-" * 70)
    print(f"STOPPED: {transcript.stopped_reason} after {len(transcript.proposals)} rounds")
    print("-" * 70)

    verdict = check_fairness(transcript, profile_a, profile_b, mock=args.mock)

    print(f"\nFAIRNESS VERDICT  (balance score: {verdict.balance_score}/100, balanced={verdict.is_balanced})")
    print(f"\n  For {profile_a.party_name}: {verdict.explanation_for_a}")
    print(f"  What they didn't know: {verdict.what_a_didnt_know}")
    print(f"\n  For {profile_b.party_name}: {verdict.explanation_for_b}")
    print(f"  What they didn't know: {verdict.what_b_didnt_know}")
    print()


if __name__ == "__main__":
    main()
