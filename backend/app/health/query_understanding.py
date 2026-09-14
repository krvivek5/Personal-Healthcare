from app.schemas.inquiry import InquiryTarget


def parse_natural_language_query(query: str) -> InquiryTarget:
    """
    Deterministic query understanding mock for testing evidence evaluation.
    Converts a natural language query into a normalized InquiryTarget.
    In a real implementation, this boundary isolates the LLM call.
    """
    query_lower = query.lower()

    domain = None
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

    entity = None
    if "lisinopril" in query_lower:
        entity = "Lisinopril"
    elif "albuterol" in query_lower:
        entity = "Albuterol"
    elif "asthma" in query_lower:
        entity = "Asthma"
    elif "peanut" in query_lower:
        entity = "Peanut"

    attributes = []
    if "dosage" in query_lower:
        attributes.append("dosage")
    if "clinic" in query_lower:
        attributes.append("clinic")
    if "blood type" in query_lower:
        attributes.append("blood_group")

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
