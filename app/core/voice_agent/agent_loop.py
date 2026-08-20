"""
Conversational voice-editing loop (blueprint Section 4.3, Mode 3).

The core behavior described in the blueprint: don't fire a clarifying
question after every utterance (exhausting), and don't generate a generic
bullet from underspecified input (useless). Only ask when the missing slot
would materially change the resulting bullet point.

`decide_next_action` is the testable decision core -- a lightweight,
explicit stand-in for the EVPI-style judgment call the LLM makes in
production. It is deliberately rule-based here so its behavior is provable
without a live model call; the production agent replaces the *judgment*
(is this slot filled well enough?) with an LLM call while keeping this same
decision contract (slots in -> ask-or-generate out).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Slot(str, Enum):
    SCOPE = "scope"  # what system/team/product
    SCALE = "scale"  # how big (users, data volume, team size)
    OUTCOME_METRIC = "outcome_metric"  # the measurable result


# A bullet point is only worth writing once we have the scope and at least
# one of {scale, outcome_metric} -- an outcome without a number is weak, a
# scale without an outcome is incomplete, but requiring all three for every
# utterance would make the conversation tedious.
REQUIRED_SLOTS = {Slot.SCOPE}
ONE_OF_SLOTS = {Slot.SCALE, Slot.OUTCOME_METRIC}


class NextAction(str, Enum):
    ASK_CLARIFYING_QUESTION = "ask_clarifying_question"
    GENERATE_HIGHLIGHT = "generate_highlight"


@dataclass
class AgentDecision:
    action: NextAction
    missing_slot: Slot | None = None
    filled_slots: dict[Slot, str] = field(default_factory=dict)


def decide_next_action(filled_slots: dict[Slot, str]) -> AgentDecision:
    """
    Pure decision function: given what's been extracted from the
    conversation so far, decide whether to ask one more question or move to
    generation.
    """
    missing_required = [s for s in REQUIRED_SLOTS if s not in filled_slots]
    if missing_required:
        return AgentDecision(NextAction.ASK_CLARIFYING_QUESTION, missing_required[0], filled_slots)

    has_one_of = any(s in filled_slots for s in ONE_OF_SLOTS)
    if not has_one_of:
        # Prefer asking for the outcome metric first -- it's the highest-value
        # missing detail for a strong, quantified bullet (blueprint Section
        # "Action Verb and Metric Analysis").
        return AgentDecision(NextAction.ASK_CLARIFYING_QUESTION, Slot.OUTCOME_METRIC, filled_slots)

    return AgentDecision(NextAction.GENERATE_HIGHLIGHT, None, filled_slots)


CLARIFYING_QUESTIONS = {
    Slot.SCOPE: "Which system or team was this? A quick name is enough.",
    Slot.SCALE: "Roughly what scale — how much data, how many users, or how big was the team?",
    Slot.OUTCOME_METRIC: "What changed as a result — a number, a percentage, or a time saved?",
}


def run_turn(
    utterance_slots: dict[Slot, str],
    accumulated_slots: dict[Slot, str] | None = None,
) -> AgentDecision:
    """
    One turn of the conversation. In production, `utterance_slots` comes
    from an LLM extraction call over the latest transcribed utterance;
    here it's passed in directly so the decision logic is unit-testable
    without a live model.
    """
    merged = {**(accumulated_slots or {}), **utterance_slots}
    return decide_next_action(merged)
