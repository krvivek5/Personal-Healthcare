import re

from app.schemas.inquiry import SafetyGuardrailState

# The fixed safety advisory message as mandated by the M1 design.
SAFETY_ADVISORY = (
    "Your inquiry mentions symptoms that may require prompt medical evaluation. "
    "Please seek professional medical care. If you believe this may be an emergency, "
    "contact your local emergency services. This system does not assess symptom "
    "severity, perform clinical triage, or provide medical diagnoses."
)

# Pattern definitions for acute symptoms
# These use regex for case-insensitive keyword matching.
# We use word boundaries \b to avoid matching sub-words.
# To keep it conservative and deterministic, we enforce proximity for modifiers.
_SAFETY_PATTERNS = [
    # severe/crushing/radiating chest pain
    r"\b(severe|crushing|radiating|intense|acute)\s+(chest\s+pain|chest\s+pressure|chest\s+tightness)\b",
    r"\b(chest\s+pain|chest\s+pressure|chest\s+tightness).{0,40}\b(severe|crushing|radiating|intense|acute)\b",
    # sudden unilateral weakness/facial drooping/numbness
    r"\b(sudden|unilateral|one-sided|one\s+sided|left-sided|right-sided)\s+(weakness|numbness|paralysis)\b",
    r"\bfacial\s+(droop|drooping)\b",
    r"\b(face|mouth)\s+(droops|drooping|drooped)\b",
    # severe acute breathing difficulty
    r"\b(severe|acute|sudden)\s+(breathing\s+difficulty|shortness\s+of\s+breath|dyspnea)\b",
    r"\bcan'?t\s+breathe\b",
    r"\bgasping\s+for\s+air\b",
    # acute anaphylaxis-type descriptions such as throat closing
    # or difficulty breathing with hives
    r"\bthroat\s+(is\s+)?closing\b",
    r"\btrouble\s+breathing.{0,40}\b(hives|swelling)\b",
    r"\b(difficulty|trouble)\s+breathing.{0,40}\b(hives|swelling)\b",
    r"\b(hives|swelling).{0,40}\b(difficulty|trouble)\s+breathing\b",
    r"\banaphylaxis\b",
    r"\banaphylactic\b",
    r"\bthroat\s+swelling\b",
    # sudden loss of consciousness
    r"\b(sudden\s+)?loss\s+of\s+consciousness\b",
    r"\bpassed\s+out\b",
    r"\bfainted\b",
    r"\bblacked\s+out\b",
    r"\bcollapsed\b",
    # severe head trauma
    r"\bsevere\s+(head\s+trauma|head\s+injury|blow\s+to\s+the\s+head)\b",
    r"\bhead\s+(trauma|injury).{0,40}\b(severe|bad|bleeding|loss\s+of\s+consciousness)\b",
    r"\bhit\s+my\s+head.{0,40}\b(hard|passed\s+out|fainted)\b",
    # explicit self-harm intent
    r"\b(kill|hurt|harm)\s+myself\b",
    r"\bcommit\s+suicide\b",
    r"\bend\s+my\s+life\b",
    r"\bwant\s+to\s+die\b",
]

_COMPILED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in _SAFETY_PATTERNS
]


def evaluate_safety(query: str) -> SafetyGuardrailState:
    """
    Evaluates a user query against a predefined, deterministic set of
    acute symptom patterns.

    Returns a SafetyGuardrailState indicating if a pattern was triggered,
    along with a fixed advisory message if triggered.
    """
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(query):
            return SafetyGuardrailState(
                triggered=True,
                advisory_message=SAFETY_ADVISORY,
            )

    return SafetyGuardrailState(triggered=False, advisory_message=None)
