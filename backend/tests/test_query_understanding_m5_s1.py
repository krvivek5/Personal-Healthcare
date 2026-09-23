from datetime import date

from app.health.query_understanding import parse_natural_language_query
from app.schemas.inquiry import RoutingMode, TemporalScope


# Dimension 1: Explicit Structured Queries
def test_explicit_structured_queries():
    # Conditions
    t = parse_natural_language_query("What are my conditions?")
    assert "conditions" in t.candidate_structured_domains
    assert t.routing_mode == RoutingMode.CROSS_DOMAIN

    # Medications (CROSS_DOMAIN because 'medications' maps to 'prescriptions' too)
    t = parse_natural_language_query("What medications am I on?")
    assert "medications" in t.candidate_structured_domains
    assert "prescriptions" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.CROSS_DOMAIN

    # Allergies
    t = parse_natural_language_query("List my allergies")
    assert "allergies" in t.candidate_structured_domains
    assert (
        t.routing_mode == RoutingMode.CROSS_DOMAIN
    )  # allergies adds clinical_documents

    # Symptoms
    t = parse_natural_language_query("I have a symptom")
    assert "symptoms" in t.candidate_structured_domains
    assert t.routing_mode == RoutingMode.STRUCTURED_ONLY

    # Goals
    t = parse_natural_language_query("What are my health goals?")
    assert "goals" in t.candidate_structured_domains
    assert t.routing_mode == RoutingMode.STRUCTURED_ONLY

    # Profile
    t = parse_natural_language_query("Show me my profile")
    assert "profile" in t.candidate_structured_domains
    assert t.routing_mode == RoutingMode.STRUCTURED_ONLY


# Dimension 2: Explicit Document Queries
def test_explicit_document_queries():
    # Labs
    t = parse_natural_language_query("What was my creatinine?")
    assert t.candidate_structured_domains == []
    assert "labs" in t.candidate_document_domains
    assert t.target_entity == "Creatinine"
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY

    # Reports
    t = parse_natural_language_query("What did my MRI show?")
    assert "reports" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY

    # Clinical Docs
    t = parse_natural_language_query("What was in my discharge summary?")
    assert "clinical_documents" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY

    # Prescriptions
    t = parse_natural_language_query("What is on my prescription?")
    assert "prescriptions" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY


# Dimension 3: Physician / Doctor
def test_physician_doctor_queries():
    t = parse_natural_language_query("What is my physician name?")
    assert "prescriptions" in t.candidate_document_domains
    assert "clinical_documents" in t.candidate_document_domains
    assert "physician_name" in t.requested_attributes
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert not t.clarification_required


# Dimension 4: Medication Synonyms
def test_medication_synonyms():
    for word in ["pill", "drug", "dose", "refill", "rx"]:
        t = parse_natural_language_query(f"What {word} was I given?")
        assert "prescriptions" in t.candidate_document_domains
        # rx adds only doc, pill adds structured
        if word in ["pill", "drug", "refill"]:
            assert "medications" in t.candidate_structured_domains
            assert t.routing_mode == RoutingMode.CROSS_DOMAIN
        else:
            assert t.routing_mode == RoutingMode.DOCUMENT_ONLY


# Dimension 5: Condition & Allergy Synonyms
def test_condition_allergy_synonyms():
    t = parse_natural_language_query("Do I have diabetes?")
    assert "conditions" in t.candidate_structured_domains
    assert t.target_entity == "Diabetes"

    t = parse_natural_language_query("I have high blood pressure")
    assert "conditions" in t.candidate_structured_domains

    t = parse_natural_language_query("penicillin allergy")
    assert "allergies" in t.candidate_structured_domains


# Dimension 6: Attribute-Only Queries
def test_attribute_only_queries():
    t = parse_natural_language_query("What is the dosage?")
    # 'dosage' is in MED_DOC_ANCHORS, so it maps to prescriptions
    assert "prescriptions" in t.candidate_document_domains
    assert "dosage" in t.requested_attributes
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert not t.clarification_required

    t = parse_natural_language_query("What clinic did I visit?")
    assert not t.candidate_structured_domains
    assert "clinical_documents" in t.candidate_document_domains
    assert "reports" in t.candidate_document_domains
    assert "clinic" in t.requested_attributes
    assert not t.clarification_required
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY


def test_s3_implicit_queries():
    t = parse_natural_language_query("What is my doctor's phone number?")
    assert "contact_number" in t.requested_attributes
    assert "physician_name" not in t.requested_attributes
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY

    t = parse_natural_language_query("What did my doctor say?")
    assert "consultation_notes" in t.requested_attributes
    assert t.target_entity is None
    assert t.routing_mode == RoutingMode.DOCUMENT_ONLY

    t = parse_natural_language_query("What is in my latest report?")
    assert t.target_entity is None
    assert t.requested_attributes == []
    assert t.temporal_constraint.scope == TemporalScope.ALL


# Dimension 7: Broad Medical-Record Queries
def test_broad_medical_record_queries():
    t = parse_natural_language_query("Show me my recent medical records")
    assert "conditions" in t.candidate_structured_domains
    assert "medications" in t.candidate_structured_domains
    assert "clinical_documents" in t.candidate_document_domains
    assert "labs" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.CROSS_DOMAIN


# Dimension 8: Cross-Domain Query Classification
def test_cross_domain_query_classification():
    t = parse_natural_language_query("Who prescribed my Lisinopril?")
    assert "medications" in t.candidate_structured_domains
    assert "prescriptions" in t.candidate_document_domains
    assert t.routing_mode == RoutingMode.CROSS_DOMAIN


# Dimension 9: True Ambiguity Clarification
def test_true_ambiguity_clarification():
    ambiguous_queries = [
        "How am I doing?",
        "Tell me something useful",
        "What should I know?",
        "Hello",
        "Can you help me?",
        "Good morning",
    ]
    for q in ambiguous_queries:
        t = parse_natural_language_query(q)
        assert t.routing_mode == RoutingMode.AMBIGUOUS_CLARIFY, f"Failed for query: {q}"
        assert t.clarification_required is True, f"Failed for query: {q}"
        assert t.clarification_prompt is not None, f"Failed for query: {q}"
        assert t.candidate_structured_domains == [], f"Failed for query: {q}"
        assert t.candidate_document_domains == [], f"Failed for query: {q}"
        assert t.requested_attributes == [], f"Failed for query: {q}"
        assert t.target_entity is None, f"Failed for query: {q}"


# Dimension 10: Unroutable Queries (Unrelated / Non-Health)
def test_unroutable_queries():
    unroutable_queries = [
        "What is the capital of France?",
        "Tell me a joke",
        "What is the weather today?",
        # Clearly non-health queries not in any blacklist:
        "Who won the World Cup?",
        "Write a python script to sort numbers",
        "What is the stock price of Apple?",
    ]
    for q in unroutable_queries:
        t = parse_natural_language_query(q)
        assert t.routing_mode == RoutingMode.UNROUTABLE, f"Failed for query: {q}"
        assert t.clarification_required is False, f"Failed for query: {q}"
        assert t.clarification_prompt is None, f"Failed for query: {q}"
        assert t.candidate_structured_domains == [], f"Failed for query: {q}"
        assert t.candidate_document_domains == [], f"Failed for query: {q}"
        assert t.target_entity is None, f"Failed for query: {q}"
        assert t.requested_attributes == [], f"Failed for query: {q}"


def test_unrecognized_medical_query_is_unroutable_not_clarify():
    # Unrecognized medical queries without recognized anchors/entities
    # must NOT be treated as generic clarification.
    t = parse_natural_language_query("What is my troponin level?")
    assert t.routing_mode == RoutingMode.UNROUTABLE
    assert t.clarification_required is False
    assert t.clarification_prompt is None


def test_routable_attribute_and_clinical_queries():
    # 1. Physician name attribute query
    t_physician = parse_natural_language_query("What is my physician name?")
    assert t_physician.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "physician_name" in t_physician.requested_attributes
    assert "prescriptions" in t_physician.candidate_document_domains
    assert "clinical_documents" in t_physician.candidate_document_domains
    assert t_physician.clarification_required is False

    # 2. Dosage attribute query
    t_dosage = parse_natural_language_query("What was the dosage?")
    assert t_dosage.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "dosage" in t_dosage.requested_attributes
    assert "prescriptions" in t_dosage.candidate_document_domains
    assert t_dosage.clarification_required is False

    # 3. Additional recognized clinical attribute query: blood type / group
    t_blood = parse_natural_language_query("What is my blood type?")
    assert t_blood.routing_mode == RoutingMode.STRUCTURED_ONLY
    assert "blood_group" in t_blood.requested_attributes
    assert "profile" in t_blood.candidate_structured_domains
    assert t_blood.clarification_required is False

    # 4. Additional recognized clinical attribute query: consultation notes
    t_notes = parse_natural_language_query("What did my doctor note say?")
    assert t_notes.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "consultation_notes" in t_notes.requested_attributes
    assert "clinical_documents" in t_notes.candidate_document_domains
    assert t_notes.clarification_required is False


# Dimension 11: Temporal Expressions
def test_temporal_expressions():
    t = parse_natural_language_query("What was my cholesterol last year?")
    assert t.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t.temporal_constraint.anchor_year == date.today().year - 1

    t = parse_natural_language_query("What was it in 2024?")
    assert t.temporal_constraint.anchor_year == 2024

    t = parse_natural_language_query("What medicines am I currently taking?")
    assert t.temporal_constraint.scope == TemporalScope.CURRENT


# Dimension 12: Architecture Lock Canonical Queries (Matrix 1-20)
def test_routing_matrix():
    queries = [
        # 1
        (
            "What was my creatinine?",
            [],
            ["labs"],
            "Creatinine",
            [],
            "historical",
            RoutingMode.DOCUMENT_ONLY,
            False,
        ),
        # 6
        (
            "What is my physician name?",
            [],
            ["prescriptions", "clinical_documents"],
            None,
            ["physician_name"],
            "all",
            RoutingMode.DOCUMENT_ONLY,
            False,
        ),
        # 7
        (
            "Who prescribed my Lisinopril?",
            ["medications"],
            ["prescriptions"],
            "Lisinopril",
            ["physician_name"],
            "all",
            RoutingMode.CROSS_DOMAIN,
            False,
        ),
        # 9
        (
            "What did my doctor say?",
            [],
            ["clinical_documents", "reports"],
            None,
            ["consultation_notes"],
            "all",
            RoutingMode.DOCUMENT_ONLY,
            False,
        ),
        # 18
        (
            "How am I doing?",
            [],
            [],
            None,
            [],
            "all",
            RoutingMode.AMBIGUOUS_CLARIFY,
            True,
        ),
        # 20
        (
            "What is the capital of France?",
            [],
            [],
            None,
            [],
            "all",
            RoutingMode.UNROUTABLE,
            False,
        ),
    ]
    for (
        q,
        exp_struct,
        exp_doc,
        exp_entity,
        exp_attr,
        exp_scope,
        exp_mode,
        exp_clar,
    ) in queries:
        t = parse_natural_language_query(q)
        for d in exp_struct:
            assert d in t.candidate_structured_domains
        for d in exp_doc:
            assert d in t.candidate_document_domains
        if exp_entity:
            assert t.target_entity == exp_entity
        for a in exp_attr:
            assert a in t.requested_attributes
        assert t.temporal_constraint.scope.value == exp_scope
        assert t.routing_mode == exp_mode
        assert t.clarification_required == exp_clar


# Dimension 13: Multi-Domain Collection Preservation
def test_collection_preservation():
    t = parse_natural_language_query("Who prescribed my Lisinopril?")
    # Access target_domain
    _ = t.target_domain
    # Ensure collections were not mutated
    assert "medications" in t.candidate_structured_domains
    assert "prescriptions" in t.candidate_document_domains


# Dimension 16: Deterministic Re-Run Consistency
def test_deterministic_rerun_consistency():
    queries = [
        "Who prescribed my Lisinopril?",
        "What was my creatinine?",
        "How am I doing?",
    ]
    for q in queries:
        first = parse_natural_language_query(q)
        for _ in range(100):
            t = parse_natural_language_query(q)
            assert t.model_dump() == first.model_dump()
