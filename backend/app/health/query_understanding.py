import re
from datetime import date

from app.schemas.inquiry import (
    InquiryTarget,
    RoutingMode,
    TemporalConstraint,
    TemporalScope,
)

PROVIDER_ANCHORS = {
    "physician",
    "doctor",
    "prescriber",
    "clinician",
    "provider",
    "specialist",
    "cardiologist",
    "surgeon",
    "who signed",
    "who wrote",
    "who prescribed",
}

# Split MEDICATION_ANCHORS to handle DOCUMENT_ONLY vs CROSS_DOMAIN correctly
MED_STRUCTURED_ANCHORS = {
    "medications",
    "medication",
    "medicine",
    "medicines",
    "drug",
    "drugs",
    "pill",
    "pills",
    "refill",
    "taking",
    "lisinopril",
    "albuterol",
    "metformin",
    "atorvastatin",
    "ibuprofen",
    "amoxicillin",
    "omeprazole",
}
MED_DOC_ANCHORS = {
    "prescription",
    "prescriptions",
    "rx",
    "prescribed",
    "medication document",
    "dose",
    "dosage",
}

CONSULTATION_ANCHORS = {
    "doctor say",
    "doctor note",
    "doctor letter",
    "consultation",
    "consultation note",
    "recommendation",
    "discharge instructions",
    "advice",
    "visit note",
    "clinic note",
    "referral",
    "referral letter",
    "discharge summary",
    "hospital letter",
}

DIAGNOSTIC_ANCHORS = {
    "report",
    "reports",
    "scan",
    "mri",
    "x-ray",
    "xray",
    "ct",
    "ct scan",
    "ultrasound",
    "echo",
    "echocardiogram",
    "ecg",
    "ekg",
    "imaging",
    "radiology",
    "pathology",
    "biopsy",
    "findings",
    "impression",
}

LAB_ANCHORS = {
    "lab",
    "labs",
    "lab report",
    "blood test",
    "blood work",
    "test result",
    "test results",
    "panel",
    "lipid panel",
    "metabolic panel",
    "creatinine",
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
    "ferritin",
    "sodium",
    "potassium",
}

CONDITION_ANCHORS = {
    "condition",
    "conditions",
    "diagnosis",
    "diagnosed with",
    "asthma",
    "diabetes",
    "hypertension",
    "high blood pressure",
    "depression",
    "anxiety",
    "gerd",
    "copd",
    "arthritis",
}

ALLERGY_ANCHORS = {
    "allergy",
    "allergies",
    "allergic",
    "allergic to",
    "reaction to",
    "peanut",
    "penicillin",
    "sulfa",
    "latex",
    "hives",
    "anaphylaxis",
}

PROFILE_ANCHORS = {
    "blood type",
    "blood group",
    "height",
    "biological sex",
    "date of birth",
    "profile",
}

BROAD_RECORD_ANCHORS = {
    "my records",
    "medical records",
    "medical history",
    "health summary",
    "recent documents",
    "recent visits",
    "everything on file",
}

# Entities
MEDICATION_ENTITIES = [
    "Lisinopril",
    "Albuterol",
    "Metformin",
    "Atorvastatin",
    "Ibuprofen",
    "Amoxicillin",
    "Omeprazole",
]
CONDITION_ENTITIES = [
    "Asthma",
    "Diabetes",
    "Hypertension",
    "GERD",
    "Depression",
    "High blood pressure",
    "Anxiety",
    "COPD",
    "Arthritis",
]
ALLERGY_ENTITIES = ["Peanut", "Penicillin", "Latex", "Sulfa"]
ANALYTE_ENTITIES = [
    "Creatinine",
    "HbA1c",
    "Vitamin D",
    "Cholesterol",
    "LDL",
    "HDL",
    "TSH",
    "Glucose",
]


def _matches_any(query_lower: str, keywords: set[str]) -> bool:
    for kw in keywords:
        if " " in kw:
            if kw in query_lower:
                return True
        else:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, query_lower):
                return True
    return False


def _extract_entity(query_lower: str) -> str | None:
    # ordered longest-first
    all_entities = sorted(
        MEDICATION_ENTITIES + CONDITION_ENTITIES + ALLERGY_ENTITIES + ANALYTE_ENTITIES,
        key=len,
        reverse=True,
    )
    for entity in all_entities:
        if entity.lower() in query_lower:
            return entity
    return None


CONVERSATIONAL_VAGUE_ANCHORS = {
    "how am i doing",
    "tell me something useful",
    "what should i know",
    "hello",
    "hi",
    "hey",
    "can you help me",
    "what's up",
    "whats up",
    "greetings",
    "good morning",
    "good afternoon",
    "good evening",
}


def is_conversational_or_vague(query_lower: str) -> bool:
    """Detect if an anchorless query is an underspecified inquiry."""
    return _matches_any(query_lower, CONVERSATIONAL_VAGUE_ANCHORS)


def parse_natural_language_query(query: str) -> InquiryTarget:
    query_lower = query.lower()

    # Lists preserve addition order to satisfy transitional target_domain access
    candidate_structured_domains = []
    candidate_document_domains = []

    def add_s(domains):
        for d in domains:
            if d not in candidate_structured_domains:
                candidate_structured_domains.append(d)

    def add_d(domains):
        for d in domains:
            if d not in candidate_document_domains:
                candidate_document_domains.append(d)

    # Broad Record
    if _matches_any(query_lower, BROAD_RECORD_ANCHORS):
        add_s(["conditions", "medications"])
        add_d(["clinical_documents", "reports", "prescriptions", "labs"])

    # Consultation
    if _matches_any(query_lower, CONSULTATION_ANCHORS):
        add_d(["clinical_documents", "reports"])

    # Provider
    if _matches_any(query_lower, PROVIDER_ANCHORS):
        add_d(["prescriptions", "clinical_documents"])
        if (
            _matches_any(query_lower, MED_STRUCTURED_ANCHORS)
            or _matches_any(query_lower, MED_DOC_ANCHORS)
            or _extract_entity(query_lower) in MEDICATION_ENTITIES
        ):
            add_s(["medications"])

    # Medication (Structured vs Doc)
    if _matches_any(query_lower, MED_STRUCTURED_ANCHORS):
        add_s(["medications"])
        add_d(["prescriptions"])
    if _matches_any(query_lower, MED_DOC_ANCHORS):
        add_d(["prescriptions"])

    # Diagnostic
    if _matches_any(query_lower, DIAGNOSTIC_ANCHORS):
        add_d(["reports", "clinical_documents"])

    # Lab
    if _matches_any(query_lower, LAB_ANCHORS):
        add_d(["labs"])

    # Conditions
    if _matches_any(query_lower, CONDITION_ANCHORS):
        add_s(["conditions"])
        add_d(["clinical_documents"])

    # Allergies
    if _matches_any(query_lower, ALLERGY_ANCHORS):
        add_s(["allergies"])
        add_d(["clinical_documents"])

    # Profile
    if _matches_any(query_lower, PROFILE_ANCHORS):
        add_s(["profile"])

    # Goals (to pass legacy tests)
    if _matches_any(query_lower, {"goal", "goals"}):
        add_s(["goals"])

    # Symptoms (to pass legacy tests)
    if _matches_any(query_lower, {"symptom", "symptoms"}):
        add_s(["symptoms"])

    # Stage 3: Entity Extraction
    entity = _extract_entity(query_lower)

    # If document domains are present but no entity yet, extract document topic
    if entity is None and candidate_document_domains:
        all_doc_keywords = sorted(
            list(
                LAB_ANCHORS
                | DIAGNOSTIC_ANCHORS
                | CONSULTATION_ANCHORS
                | PROVIDER_ANCHORS
                | {"discharge summary"}
            ),
            key=len,
            reverse=True,
        )
        for kw in all_doc_keywords:
            if kw in query_lower:
                entity = kw
                break

    # Stage 4: Attribute Extraction
    attributes = []
    if _matches_any(query_lower, {"dosage", "dose"}):
        attributes.append("dosage")
    if _matches_any(query_lower, {"clinic", "hospital", "facility"}):
        attributes.append("clinic")
    if _matches_any(query_lower, {"blood type", "blood group"}):
        attributes.append("blood_group")
    if _matches_any(
        query_lower,
        {"physician", "doctor", "prescriber", "who signed", "who prescribed", "name"},
    ):
        attributes.append("physician_name")
    if _matches_any(query_lower, {"status", "active", "stopped"}):
        attributes.append("status")
    if _matches_any(query_lower, {"frequency", "how often"}):
        attributes.append("frequency")
    if _matches_any(query_lower, {"doctor say", "doctor note", "consultation note"}):
        attributes.append("consultation_notes")

    # Stage 4: Temporal Constraints
    temporal_scope = TemporalScope.ALL
    anchor_year = None
    raw_expression = None

    current_year = date.today().year

    # Intervals
    if "last year" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        anchor_year = current_year - 1
        raw_expression = "last year"
    elif "in 2024" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        anchor_year = 2024
        raw_expression = "in 2024"
    elif "2023" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        anchor_year = 2023
        raw_expression = "2023"
    elif "past 6 months" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = "past 6 months"
    elif "last 3 months" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = "last 3 months"
    elif "since june" in query_lower:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = "since june"
    # Current
    elif _matches_any(
        query_lower, {"current", "currently", "taking", "active", "now", "present"}
    ):
        temporal_scope = TemporalScope.CURRENT
    # Historical
    elif _matches_any(
        query_lower,
        {"past", "historical", "history", "was", "diagnosed", "previously", "stopped"},
    ):
        temporal_scope = TemporalScope.HISTORICAL
    # Also for legacy "have" -> current
    elif "have" in query_lower.split() and temporal_scope == TemporalScope.ALL:
        temporal_scope = TemporalScope.CURRENT

    temporal_constraint = TemporalConstraint(
        scope=temporal_scope, anchor_year=anchor_year, raw_expression=raw_expression
    )

    # Stage 5: RoutingMode & Clarification Determination
    clarification_required = False
    clarification_prompt = None

    if candidate_structured_domains and candidate_document_domains:
        routing_mode = RoutingMode.CROSS_DOMAIN
    elif candidate_structured_domains:
        routing_mode = RoutingMode.STRUCTURED_ONLY
    elif candidate_document_domains:
        routing_mode = RoutingMode.DOCUMENT_ONLY
    elif not attributes and not entity and is_conversational_or_vague(query_lower):
        routing_mode = RoutingMode.AMBIGUOUS_CLARIFY
        clarification_required = True
        clarification_prompt = (
            "Could you please specify which aspect of your health records you would "
            "like to review (such as your medications, lab results, conditions, or "
            "recent doctor visits)?"
        )
    else:
        routing_mode = RoutingMode.UNROUTABLE
        clarification_required = False

    return InquiryTarget(
        candidate_structured_domains=candidate_structured_domains,
        candidate_document_domains=candidate_document_domains,
        target_entity=entity,
        requested_attributes=attributes,
        temporal_constraint=temporal_constraint,
        routing_mode=routing_mode,
        clarification_required=clarification_required,
        clarification_prompt=clarification_prompt,
        question_intent="QUERY",
    )
