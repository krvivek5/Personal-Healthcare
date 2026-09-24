import calendar
import re
from datetime import date, datetime, timedelta, timezone

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
    "recently",
    "lately",
    "a while ago",
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

    # Stage 4: Attribute Extraction
    attributes = []
    if _matches_any(query_lower, {"dosage", "dose", "strength", "amount", "how much"}):
        attributes.append("dosage")
    if _matches_any(
        query_lower,
        {
            "clinic",
            "hospital",
            "facility",
            "practice",
            "health center",
            "medical center",
        },
    ):
        attributes.append("clinic")
    if _matches_any(query_lower, {"blood type", "blood group"}):
        attributes.append("blood_group")
    if _matches_any(
        query_lower, {"status", "active", "stopped", "discontinued", "resolved"}
    ):
        attributes.append("status")
    if _matches_any(query_lower, {"frequency", "how often", "schedule", "interval"}):
        attributes.append("frequency")
    if _matches_any(
        query_lower,
        {
            "doctor say",
            "doctor note",
            "consultation",
            "advice",
            "recommendation",
            "instructions",
        },
    ):
        attributes.append("consultation_notes")
    if _matches_any(
        query_lower, {"phone", "phone number", "telephone", "contact", "fax", "call"}
    ):
        attributes.append("contact_number")

    if _matches_any(
        query_lower,
        {
            "physician",
            "doctor",
            "prescriber",
            "clinician",
            "provider",
            "who signed",
            "who wrote",
            "who prescribed",
        },
    ):
        if (
            "contact_number" not in attributes
            and "consultation_notes" not in attributes
        ):
            attributes.append("physician_name")

    # Stage 4: Temporal Constraints
    temporal_scope = TemporalScope.ALL
    start_date = None
    end_date = None
    anchor_year = None
    raw_expression = None
    unroutable = False

    ref_date = datetime.now(timezone.utc).date()
    ref_year = ref_date.year

    MONTHS = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }

    m_days = re.search(r"(past|last)\s+(\d+)\s+days?", query_lower)
    m_months = re.search(r"(past|last)\s+(\d+)\s+months?", query_lower)
    m_between = re.search(r"between\s+(\d{4})\s+and\s+(\d{4})", query_lower)
    m_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", query_lower)
    m_month_year = re.search(
        r"\b(" + "|".join(MONTHS.keys()) + r")\s+(\d{4})\b", query_lower
    )
    m_cal_date = re.search(
        r"(on\s+)?(" + "|".join(MONTHS.keys()) + r")\s+(\d{1,2}),?\s+(\d{4})",
        query_lower,
    )
    m_in_year = re.search(r"in\s+(\d{4})", query_lower)
    m_year = re.search(r"\b(20\d{2})\b", query_lower)

    if _matches_any(query_lower, {"latest", "newest", "most recent", "first"}):
        temporal_scope = TemporalScope.ALL
    elif m_days:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_days.group(0)
        days = int(m_days.group(2))
        start_date = ref_date - timedelta(days=days)
        end_date = ref_date
    elif m_months:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_months.group(0)
        months = int(m_months.group(2))
        start_date = ref_date - timedelta(days=30 * months)
        end_date = ref_date
    elif m_between:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_between.group(0)
        y1 = int(m_between.group(1))
        y2 = int(m_between.group(2))
        if y1 > y2:
            unroutable = True
        else:
            start_date = date(y1, 1, 1)
            end_date = date(y2, 12, 31)
    elif m_iso:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_iso.group(0)
        try:
            d = date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
            start_date = d
            end_date = d
            anchor_year = d.year
        except ValueError:
            unroutable = True
    elif m_cal_date:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_cal_date.group(0)
        month_str = m_cal_date.group(2)
        day = int(m_cal_date.group(3))
        year = int(m_cal_date.group(4))
        try:
            d = date(year, MONTHS[month_str], day)
            start_date = d
            end_date = d
            anchor_year = year
        except ValueError:
            unroutable = True
    elif m_month_year:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_month_year.group(0)
        month_str = m_month_year.group(1)
        year = int(m_month_year.group(2))
        month = MONTHS[month_str]
        try:
            start_date = date(year, month, 1)
            end_date = date(year, month, calendar.monthrange(year, month)[1])
            anchor_year = year
        except ValueError:
            unroutable = True
    elif _matches_any(query_lower, {"last year", "past year"}):
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = "last year" if "last year" in query_lower else "past year"
        anchor_year = ref_year - 1
        start_date = date(anchor_year, 1, 1)
        end_date = date(anchor_year, 12, 31)
    elif _matches_any(query_lower, {"this year", "current year"}):
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = "this year" if "this year" in query_lower else "current year"
        anchor_year = ref_year
        start_date = date(anchor_year, 1, 1)
        end_date = date(anchor_year, 12, 31)
    elif m_in_year:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_in_year.group(0)
        anchor_year = int(m_in_year.group(1))
        start_date = date(anchor_year, 1, 1)
        end_date = date(anchor_year, 12, 31)
    elif m_year:
        temporal_scope = TemporalScope.INTERVAL
        raw_expression = m_year.group(0)
        anchor_year = int(m_year.group(1))
        start_date = date(anchor_year, 1, 1)
        end_date = date(anchor_year, 12, 31)
    elif _matches_any(
        query_lower, {"current", "currently", "taking", "active", "now", "present"}
    ):
        temporal_scope = TemporalScope.CURRENT
    elif _matches_any(
        query_lower,
        {"past", "historical", "history", "was", "diagnosed", "previously", "stopped"},
    ):
        temporal_scope = TemporalScope.HISTORICAL
    elif "have" in query_lower.split() and temporal_scope == TemporalScope.ALL:
        temporal_scope = TemporalScope.CURRENT

    if _matches_any(query_lower, {"recently", "lately", "a while ago"}):
        if attributes or entity:
            temporal_scope = TemporalScope.ALL

    temporal_constraint = TemporalConstraint(
        scope=temporal_scope,
        start_date=start_date,
        end_date=end_date,
        anchor_year=anchor_year,
        raw_expression=raw_expression,
    )

    # Explicit Clinic Routing
    if _matches_any(
        query_lower,
        {
            "clinic",
            "hospital",
            "facility",
            "practice",
            "health center",
            "medical center",
        },
    ):
        add_d(["clinical_documents", "reports"])

    # Stage 5: RoutingMode & Clarification Determination
    clarification_required = False
    clarification_prompt = None

    if unroutable:
        routing_mode = RoutingMode.UNROUTABLE
    elif candidate_structured_domains and candidate_document_domains:
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
