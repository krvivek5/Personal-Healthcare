import re

from app.schemas.inquiry import InquiryTarget

# ---------------------------------------------------------------------------
# Document-oriented domain keywords
# ---------------------------------------------------------------------------
# These map deterministic surface-form patterns onto canonical domain names.
# The canonical names are:
#   "labs"               – laboratory / blood-test reports
#   "reports"            – generic clinical reports (radiology, pathology …)
#   "clinical_documents" – discharge summaries, clinic letters, referrals
#   "prescriptions"      – document-based prescription / medication records
#
# NOTE: "prescriptions" overlaps with the structured "medications" domain.
# When a query references both a prescription document AND a structured entity,
# the structured domain wins (see precedence order in the parser below).
# ---------------------------------------------------------------------------

_LAB_KEYWORDS = {
    "lab",
    "labs",
    "lab report",
    "blood test",
    "blood work",
    "test result",
    "test results",
    "creatinine",
    "hemoglobin",
    "hba1c",
    "glucose",
    "cholesterol",
    "ldl",
    "hdl",
    "triglyceride",
    "vitamin d",
    "vitamin b12",
    "tsh",
    "thyroid",
    "cbc",
    "complete blood count",
    "urine",
    "urinalysis",
    "culture",
    "culture report",
    "biopsy",
    "panel",
    "lipid panel",
    "metabolic panel",
    "esr",
    "crp",
    "wbc",
    "rbc",
    "platelet",
    "ferritin",
    "iron",
    "sodium",
    "potassium",
    "calcium",
    "magnesium",
    "phosphorus",
    "albumin",
    "bilirubin",
    "alt",
    "ast",
    "ggt",
    "alkaline phosphatase",
    "creatinine clearance",
    "gfr",
    "uric acid",
    "fibrinogen",
    "inr",
    "pt",
    "ptt",
    "d-dimer",
    "troponin",
    "bnp",
    "psa",
    "cortisol",
    "insulin",
    "procalcitonin",
}

_REPORT_KEYWORDS = {
    "report",
    "reports",
    "scan",
    "x-ray",
    "xray",
    "mri",
    "ct",
    "ct scan",
    "ultrasound",
    "ecg",
    "ekg",
    "echocardiogram",
    "echo",
    "endoscopy",
    "colonoscopy",
    "imaging",
    "radiology",
    "pathology",
    "biopsy report",
    "histology",
    "spirometry",
    "pulmonary function",
    "pft",
}

_CLINICAL_DOC_KEYWORDS = {
    "discharge summary",
    "discharge",
    "hospital letter",
    "clinic letter",
    "referral",
    "referral letter",
    "consultation note",
    "consultation",
    "operative note",
    "surgical note",
    "clinical document",
    "clinical note",
    "doctor note",
    "doctor letter",
    "specialist letter",
    "outpatient letter",
    "inpatient summary",
    "admission summary",
}

_PRESCRIPTION_DOC_KEYWORDS = {
    "prescription",
    "prescriptions",
    "rx",
    "prescribed",
    "medication document",
    "medication letter",
    "drug chart",
    "medicine chart",
    "discharge medications",
    "discharge prescription",
}


def _matches_any(query_lower: str, keywords: set[str]) -> bool:
    """Return True if any keyword phrase appears in the lower-cased query.

    Single-token keywords use word-boundary matching to avoid false positives
    (e.g. ``"pt"`` inside ``"appointment"`` or ``"rx"`` inside
    ``"prescription"``).
    Multi-word phrases use simple substring matching because whitespace provides
    implicit boundaries.
    """
    for kw in keywords:
        if " " in kw:
            if kw in query_lower:
                return True
        else:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, query_lower):
                return True
    return False


def parse_natural_language_query(query: str) -> InquiryTarget:
    """
    Deterministic query understanding parser.

    Converts a natural language query into a normalised InquiryTarget.
    All classification is rule-based; no LLM is used.

    Domain precedence (first match wins):
      1. Structured domains (medications, conditions, allergies, symptoms,
         goals, profile) — preserves all existing M1/M2 behaviour.
      2. Document-oriented domains (labs, reports, clinical_documents,
         prescriptions) — added by M3 Slice 4.
      3. None — when no recognisable pattern is found.
    """
    query_lower = query.lower()

    # ------------------------------------------------------------------
    # 1. Structured domains (existing M1/M2 — must remain first)
    # ------------------------------------------------------------------
    domain: str | None = None

    if (
        "medication" in query_lower
        or "lisinopril" in query_lower
        or "albuterol" in query_lower
    ):
        domain = "medications"
    elif "condition" in query_lower or "asthma" in query_lower:
        domain = "conditions"
    elif "allergy" in query_lower or "peanut" in query_lower:
        domain = "allergies"
    elif "symptom" in query_lower:
        domain = "symptoms"
    elif "goal" in query_lower:
        domain = "goals"
    elif "blood type" in query_lower or "profile" in query_lower:
        domain = "profile"

    # ------------------------------------------------------------------
    # 2. Document-oriented domains (M3 Slice 4 — only if no structured
    #    domain was matched above)
    # ------------------------------------------------------------------
    elif _matches_any(query_lower, _LAB_KEYWORDS):
        domain = "labs"
    elif _matches_any(query_lower, _REPORT_KEYWORDS):
        domain = "reports"
    elif _matches_any(query_lower, _PRESCRIPTION_DOC_KEYWORDS):
        domain = "prescriptions"
    elif _matches_any(query_lower, _CLINICAL_DOC_KEYWORDS):
        domain = "clinical_documents"

    # ------------------------------------------------------------------
    # Entity extraction (structured — unchanged from M1/M2)
    # ------------------------------------------------------------------
    entity: str | None = None
    if "lisinopril" in query_lower:
        entity = "Lisinopril"
    elif "albuterol" in query_lower:
        entity = "Albuterol"
    elif "asthma" in query_lower:
        entity = "Asthma"
    elif "peanut" in query_lower:
        entity = "Peanut"

    # ------------------------------------------------------------------
    # Attribute extraction (structured — unchanged from M1/M2)
    # ------------------------------------------------------------------
    attributes: list[str] = []
    if "dosage" in query_lower:
        attributes.append("dosage")
    if "clinic" in query_lower:
        attributes.append("clinic")
    if "blood type" in query_lower:
        attributes.append("blood_group")

    # ------------------------------------------------------------------
    # For document-oriented domains, capture the topical entity from the
    # query text so the evidence evaluator can perform keyword matching.
    # e.g. "What was my creatinine?" -> entity = "creatinine"
    # We only attempt this when a document domain was detected and no
    # structured entity was already extracted.
    # ------------------------------------------------------------------
    if domain in ("labs", "reports", "clinical_documents", "prescriptions"):
        if entity is None:
            entity = _extract_document_topic(query_lower)

    # ------------------------------------------------------------------
    # Temporal scope (unchanged from M1/M2)
    # ------------------------------------------------------------------
    temporal_scope = "all"
    if (
        "current" in query_lower
        or "taking" in query_lower
        or "have" in query_lower.split()
    ):
        temporal_scope = "current"
    if (
        "past" in query_lower
        or "historical" in query_lower
        or "diagnosed" in query_lower
        or "was" in query_lower.split()
    ):
        temporal_scope = "historical"

    return InquiryTarget(
        target_domain=domain,
        target_entity=entity,
        requested_attributes=attributes,
        temporal_scope=temporal_scope,
        question_intent="QUERY",
    )


def _extract_document_topic(query_lower: str) -> str | None:
    """
    Best-effort extraction of the primary topic/analyte from a document-
    oriented query.  Returns the longest matching keyword phrase found in
    the query, or None if nothing specific is identified.

    This is deterministic keyword matching only — no inference.
    """
    # Candidate phrases ordered longest-first to prefer specific phrases
    # (e.g. "vitamin d" before "vitamin").
    candidates: list[str] = sorted(
        _LAB_KEYWORDS
        | _REPORT_KEYWORDS
        | _CLINICAL_DOC_KEYWORDS
        | _PRESCRIPTION_DOC_KEYWORDS,
        key=len,
        reverse=True,
    )
    for phrase in candidates:
        if phrase in query_lower:
            return phrase
    return None
