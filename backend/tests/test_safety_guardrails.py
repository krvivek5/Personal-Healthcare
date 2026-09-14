import inspect

from app.health.safety_guardrails import SAFETY_ADVISORY, evaluate_safety
from app.schemas.inquiry import SafetyGuardrailState


# 1. no-match query
def test_no_match_query():
    state = evaluate_safety("What is my blood type?")
    assert not state.triggered
    assert state.advisory_message is None


# 2. chest-pain pattern
def test_chest_pain_pattern():
    state = evaluate_safety("I have severe chest pain right now.")
    assert state.triggered
    assert state.advisory_message == SAFETY_ADVISORY

    state = evaluate_safety("I am feeling a crushing chest pressure.")
    assert state.triggered


# 3. unilateral weakness/facial-droop pattern
def test_unilateral_weakness_pattern():
    state = evaluate_safety("My facial drooping started suddenly.")
    assert state.triggered

    state = evaluate_safety("I have sudden weakness on my left side.")
    assert state.triggered


# 4. acute breathing difficulty
def test_acute_breathing_difficulty():
    state = evaluate_safety("I can't breathe.")
    assert state.triggered

    state = evaluate_safety("Experiencing severe shortness of breath.")
    assert state.triggered


# 5. anaphylaxis pattern
def test_anaphylaxis_pattern():
    state = evaluate_safety("My throat is closing up after eating peanuts.")
    assert state.triggered

    state = evaluate_safety("I have trouble breathing and hives everywhere.")
    assert state.triggered


# 6. loss-of-consciousness pattern
def test_loss_of_consciousness_pattern():
    state = evaluate_safety("I passed out for a few minutes.")
    assert state.triggered

    state = evaluate_safety("Sudden loss of consciousness earlier.")
    assert state.triggered


# 7. severe-head-trauma pattern
def test_severe_head_trauma_pattern():
    state = evaluate_safety("I had a severe head injury from falling.")
    assert state.triggered

    state = evaluate_safety("I hit my head hard and passed out.")
    assert state.triggered


# 8. explicit self-harm pattern
def test_explicit_self_harm_pattern():
    state = evaluate_safety("I want to hurt myself.")
    assert state.triggered

    state = evaluate_safety("Thinking about how to commit suicide.")
    assert state.triggered


# 9. case-insensitive matching
def test_case_insensitive_matching():
    state1 = evaluate_safety("SEVERE CHEST PAIN")
    state2 = evaluate_safety("severe chest pain")
    assert state1.triggered and state2.triggered


# 10. fixed advisory exactness
def test_fixed_advisory_exactness():
    state = evaluate_safety("I fainted.")
    assert state.triggered
    assert state.advisory_message == (
        "Your inquiry mentions symptoms that may require prompt medical evaluation. "
        "Please seek professional medical care. If you believe this may be an "
        "emergency, contact your local emergency services. This system does not "
        "assess symptom severity, perform clinical triage, or provide medical "
        "diagnoses."
    )


# 11. no diagnosis/triage/treatment logic in output
def test_no_clinical_logic_in_output():
    state = evaluate_safety("severe chest pain")
    # Check that the output is exactly SafetyGuardrailState and nothing more
    # The string must not contain diagnoses or treatment recommendations
    assert isinstance(state, SafetyGuardrailState)
    assert (
        "triage" in state.advisory_message
    )  # Because it says "does not perform clinical triage"
    assert "myocardial infarction" not in state.advisory_message
    assert "take aspirin" not in state.advisory_message


# 12. near-miss/non-triggering ordinary health queries
def test_near_miss_ordinary_queries():
    state = evaluate_safety("I have mild chest discomfort sometimes after meals.")
    # Based on our regex, "mild chest discomfort" doesn't trigger "severe chest pain"
    assert not state.triggered

    state = evaluate_safety("I am breathing fine now.")
    assert not state.triggered

    state = evaluate_safety("I hit my toe hard.")
    assert not state.triggered


# 13. multiple matching patterns still produce one deterministic safety state
def test_multiple_patterns_one_state():
    state = evaluate_safety(
        "I have severe chest pain and I passed out, also my throat is closing."
    )
    assert state.triggered
    assert state.advisory_message == SAFETY_ADVISORY


# 14. repeated execution produces identical results
def test_repeated_execution_identical_results():
    query = "I have severe shortness of breath."
    state1 = evaluate_safety(query)
    state2 = evaluate_safety(query)
    state3 = evaluate_safety(query)

    assert state1.triggered == state2.triggered == state3.triggered is True
    assert state1.advisory_message == state2.advisory_message == state3.advisory_message


# Verify no database, identity, or LLM access in the interface
def test_safety_signature():
    sig = inspect.signature(evaluate_safety)
    assert "db" not in sig.parameters
    assert "patient_id" not in sig.parameters
    assert "user_id" not in sig.parameters
    assert "llm" not in sig.parameters
    assert list(sig.parameters.keys()) == ["query"]
