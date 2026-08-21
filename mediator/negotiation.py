"""
The negotiation loop controller — orchestrates Agent A and Agent B through
bounded rounds until they converge or hit the round cap.

Stopping conditions (Phase 1 design):
  1. mutual_accept        — the current speaker's action is ACCEPT, before
                             the forced-convergence round
  2. forced_convergence   — FORCE_ACCEPT_ROUND reached; the loop itself
                             (not the LLM) locks in the other side's last
                             offer. This is a hard guarantee, not a prompt
                             suggestion — an LLM that keeps proposing
                             instead of accepting cannot stall the
                             negotiation past this round, no matter what
                             the model decides to do.
  3. max_rounds           — reserved fallback; should not normally be hit
                             now that forced_convergence exists, but kept
                             as a safety net in case FORCE_ACCEPT_ROUND is
                             ever raised above MAX_ROUNDS by mistake.
  4. hard_constraint_conflict — reserved for future validation that checks
                             a proposal against the OTHER party's hard
                             constraints before it's allowed to stand (not
                             needed for MVP since agents never see the other
                             side's hard constraints directly)
"""

from __future__ import annotations

from .agents import BaseAgent
from .schema import NegotiationTranscript, Proposal, ProposalAction

MAX_ROUNDS = 8
# By this round, the loop forces acceptance regardless of what the agent
# returns. Keep this <= MAX_ROUNDS. Prompt-level instructions ask agents to
# converge earlier than this on their own — this is the backstop for when
# a model doesn't reliably follow that instruction (which happens).
FORCE_ACCEPT_ROUND = 7


def run_negotiation(
    room_code: str,
    agent_a: BaseAgent,
    agent_b: BaseAgent,
    max_rounds: int = MAX_ROUNDS,
    force_accept_round: int = FORCE_ACCEPT_ROUND,
    on_round: callable = None,
) -> NegotiationTranscript:
    """
    Runs the full negotiation loop and returns the transcript.

    on_round: optional callback(proposal: Proposal) — useful for streaming
    live status to a frontend ("Agent A proposing...") without coupling
    this module to any transport layer.
    """
    transcript = NegotiationTranscript(
        room_code=room_code,
        party_a=agent_a.profile.party_name,
        party_b=agent_b.profile.party_name,
    )

    speakers = [agent_a, agent_b]
    other_last: Proposal | None = None

    for round_number in range(1, max_rounds + 1):
        speaker = speakers[(round_number - 1) % 2]
        proposal = speaker.next_move(round_number, other_last)

        # Hard guarantee: once we hit force_accept_round, convergence is
        # enforced by the CODE, not requested via prompt. If the agent
        # returned anything other than ACCEPT, override it. This is what
        # actually prevents an 8-round stall regardless of which model or
        # provider is behind the agent.
        forced = False
        if (
            other_last is not None
            and round_number >= force_accept_round
            and proposal.action != ProposalAction.ACCEPT
        ):
            proposal = Proposal(
                round_number=round_number,
                speaker=proposal.speaker,
                action=ProposalAction.ACCEPT,
                terms=other_last.terms,
                rationale=f"(auto-converged — round cap reached) {proposal.rationale}",
                conceded_on=[],
            )
            forced = True

        transcript.proposals.append(proposal)

        if on_round:
            on_round(proposal)

        if proposal.action == ProposalAction.ACCEPT:
            transcript.final_terms = other_last.terms if other_last else proposal.terms
            transcript.stopped_reason = "forced_convergence" if forced else "mutual_accept"
            return transcript

        other_last = proposal

    # Should not normally be reached — forced_convergence guarantees a stop
    # by force_accept_round — but kept as a safety net.
    transcript.final_terms = other_last.terms if other_last else []
    transcript.stopped_reason = "max_rounds"
    return transcript
