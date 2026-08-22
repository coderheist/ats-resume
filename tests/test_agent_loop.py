from app.core.voice_agent.agent_loop import NextAction, Slot, run_turn


def test_asks_for_scope_when_nothing_known():
    decision = run_turn(utterance_slots={})
    assert decision.action == NextAction.ASK_CLARIFYING_QUESTION
    assert decision.missing_slot == Slot.SCOPE


def test_asks_for_outcome_when_scope_known_but_no_metric():
    decision = run_turn(utterance_slots={Slot.SCOPE: "the payments database"})
    assert decision.action == NextAction.ASK_CLARIFYING_QUESTION
    assert decision.missing_slot == Slot.OUTCOME_METRIC


def test_generates_once_scope_and_outcome_are_known():
    decision = run_turn(
        utterance_slots={
            Slot.SCOPE: "the payments database",
            Slot.OUTCOME_METRIC: "cut query latency by 40%",
        }
    )
    assert decision.action == NextAction.GENERATE_HIGHLIGHT


def test_scale_alone_also_satisfies_the_one_of_requirement():
    decision = run_turn(
        utterance_slots={
            Slot.SCOPE: "the payments database",
            Slot.SCALE: "10,000 concurrent users",
        }
    )
    assert decision.action == NextAction.GENERATE_HIGHLIGHT


def test_slots_accumulate_across_turns():
    turn1 = run_turn(utterance_slots={Slot.SCOPE: "the payments database"})
    turn2 = run_turn(
        utterance_slots={Slot.OUTCOME_METRIC: "cut query latency by 40%"},
        accumulated_slots=turn1.filled_slots,
    )
    assert turn2.action == NextAction.GENERATE_HIGHLIGHT
    assert turn2.filled_slots[Slot.SCOPE] == "the payments database"
