from datetime import date, datetime, timezone
from unittest.mock import patch

from app.health.query_understanding import parse_natural_language_query
from app.schemas.inquiry import (
    RoutingMode,
    SuperlativeType,
    TemporalScope,
)


def test_latest_superlative_aliases():
    """Verify all LATEST aliases extract canonical SuperlativeType.LATEST."""
    cases = [
        ("What is my latest cholesterol?", "latest"),
        ("What is my newest prescription?", "newest"),
        ("What is my most recent blood test?", "most recent"),
        ("What was my last prescription?", "last"),
        ("What was my recent blood test?", "recent"),
    ]
    for q, alias in cases:
        t = parse_natural_language_query(q)
        assert (
            t.temporal_constraint.superlative == SuperlativeType.LATEST
        ), f"Failed to extract LATEST for alias '{alias}' in query: '{q}'"


def test_first_superlative_aliases():
    """Verify all FIRST aliases extract canonical SuperlativeType.FIRST."""
    cases = [
        ("What was my first blood pressure measurement?", "first"),
        ("What was my earliest recorded medication?", "earliest"),
        ("What was my oldest prescription?", "oldest"),
        ("What was my initial lab test?", "initial"),
    ]
    for q, alias in cases:
        t = parse_natural_language_query(q)
        assert (
            t.temporal_constraint.superlative == SuperlativeType.FIRST
        ), f"Failed to extract FIRST for alias '{alias}' in query: '{q}'"


def test_benchmark_sup02_and_sup06_full_routing():
    """Verify complete routing, domain, scope, and superlative for SUP-02 and
    SUP-06.
    """
    # SUP-02
    t_sup02 = parse_natural_language_query("What is my newest prescription?")
    assert t_sup02.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t_sup02.candidate_document_domains == ["prescriptions"]
    assert t_sup02.temporal_constraint.scope == TemporalScope.ALL
    assert t_sup02.temporal_constraint.superlative == SuperlativeType.LATEST

    # SUP-06
    t_sup06 = parse_natural_language_query(
        "What was my earliest recorded medication?"
    )
    assert t_sup06.routing_mode == RoutingMode.CROSS_DOMAIN
    assert t_sup06.candidate_structured_domains == ["medications"]
    assert t_sup06.candidate_document_domains == ["prescriptions"]
    assert t_sup06.temporal_constraint.scope == TemporalScope.ALL
    assert t_sup06.temporal_constraint.superlative == SuperlativeType.FIRST


def test_unbounded_superlatives_scope_all():
    """Verify unbounded superlative queries map to TemporalScope.ALL."""
    t_latest = parse_natural_language_query("What is my latest cholesterol?")
    assert t_latest.temporal_constraint.scope == TemporalScope.ALL
    assert t_latest.temporal_constraint.superlative == SuperlativeType.LATEST

    t_first = parse_natural_language_query(
        "What was my first blood pressure measurement?"
    )
    assert t_first.temporal_constraint.scope == TemporalScope.ALL
    assert t_first.temporal_constraint.superlative == SuperlativeType.FIRST


def test_interval_superlative_composition():
    """Verify orthogonal composition: superlatives do not prevent interval parsing."""
    # SUP-04: Latest in 2024
    t1 = parse_natural_language_query("What was my latest lab report in 2024?")
    assert t1.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "labs" in t1.candidate_document_domains
    assert t1.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t1.temporal_constraint.anchor_year == 2024
    assert t1.temporal_constraint.start_date == date(2024, 1, 1)
    assert t1.temporal_constraint.end_date == date(2024, 12, 31)
    assert t1.temporal_constraint.superlative == SuperlativeType.LATEST

    # SUP-08: First in 2023
    t2 = parse_natural_language_query("What was my first lab test in 2023?")
    assert t2.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "labs" in t2.candidate_document_domains
    assert t2.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t2.temporal_constraint.anchor_year == 2023
    assert t2.temporal_constraint.start_date == date(2023, 1, 1)
    assert t2.temporal_constraint.end_date == date(2023, 12, 31)
    assert t2.temporal_constraint.superlative == SuperlativeType.FIRST

    # Composition with date interval between years
    t3 = parse_natural_language_query(
        "What was my last blood pressure reading between 2022 and 2024?"
    )
    assert t3.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t3.temporal_constraint.start_date == date(2022, 1, 1)
    assert t3.temporal_constraint.end_date == date(2024, 12, 31)
    assert t3.temporal_constraint.superlative == SuperlativeType.LATEST


def test_explicit_current_and_historical_superlatives():
    """Verify explicit CURRENT and HISTORICAL constraints are preserved with
    superlatives.
    """
    # CURRENT + LATEST
    t1 = parse_natural_language_query("What is my latest active prescription?")
    assert t1.temporal_constraint.scope == TemporalScope.CURRENT
    assert t1.temporal_constraint.superlative == SuperlativeType.LATEST

    t2 = parse_natural_language_query("What is my newest current medication?")
    assert t2.temporal_constraint.scope == TemporalScope.CURRENT
    assert t2.temporal_constraint.superlative == SuperlativeType.LATEST

    # HISTORICAL + FIRST
    t3 = parse_natural_language_query("What was my first discontinued medication?")
    assert t3.temporal_constraint.scope == TemporalScope.HISTORICAL
    assert t3.temporal_constraint.superlative == SuperlativeType.FIRST

    t4 = parse_natural_language_query("What was my earliest resolved condition?")
    assert t4.temporal_constraint.scope == TemporalScope.HISTORICAL
    assert t4.temporal_constraint.superlative == SuperlativeType.FIRST


def test_diagnosed_superlative_override_and_m5_preservation():
    """Verify diagnosed scope upgrades to ALL under superlative, preserving
    M5 default.
    """
    # M5 default preserved when no superlative is present
    t_m5 = parse_natural_language_query(
        "Show conditions I was diagnosed with in the past"
    )
    assert t_m5.temporal_constraint.scope == TemporalScope.HISTORICAL
    assert t_m5.temporal_constraint.superlative is None

    # M6 upgrade: superlative overrides generic diagnosed to ALL
    t_first = parse_natural_language_query("What was my first diagnosed condition?")
    assert t_first.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "conditions" in t_first.candidate_structured_domains
    assert "clinical_documents" in t_first.candidate_document_domains
    assert t_first.temporal_constraint.scope == TemporalScope.ALL
    assert t_first.temporal_constraint.superlative == SuperlativeType.FIRST

    t_latest = parse_natural_language_query("What was my latest diagnosed condition?")
    assert t_latest.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "conditions" in t_latest.candidate_structured_domains
    assert "clinical_documents" in t_latest.candidate_document_domains
    assert t_latest.temporal_constraint.scope == TemporalScope.ALL
    assert t_latest.temporal_constraint.superlative == SuperlativeType.LATEST


def test_vague_recency_anchored_vs_anchorless():
    """Verify anchorless vague recency requires clarification; anchored maps
    to LATEST.
    """
    # Anchorless -> AMBIGUOUS_CLARIFY, superlative=None
    t_vague1 = parse_natural_language_query("How am I doing lately?")
    assert t_vague1.routing_mode == RoutingMode.AMBIGUOUS_CLARIFY
    assert t_vague1.clarification_required is True
    assert t_vague1.temporal_constraint.superlative is None

    t_vague2 = parse_natural_language_query("How am I doing recently?")
    assert t_vague2.routing_mode == RoutingMode.AMBIGUOUS_CLARIFY
    assert t_vague2.clarification_required is True
    assert t_vague2.temporal_constraint.superlative is None

    # Anchored -> ROUTABLE, scope=ALL, superlative=LATEST
    t_anchored1 = parse_natural_language_query(
        "What was my blood pressure recently?"
    )
    assert t_anchored1.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "clinical_documents" in t_anchored1.candidate_document_domains
    assert "reports" in t_anchored1.candidate_document_domains
    assert t_anchored1.target_entity == "blood pressure"
    assert t_anchored1.temporal_constraint.scope == TemporalScope.ALL
    assert t_anchored1.temporal_constraint.superlative == SuperlativeType.LATEST
    assert t_anchored1.clarification_required is False

    t_anchored2 = parse_natural_language_query("What were my medications lately?")
    assert t_anchored2.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "medications" in t_anchored2.candidate_structured_domains
    assert t_anchored2.temporal_constraint.scope == TemporalScope.ALL
    assert t_anchored2.temporal_constraint.superlative == SuperlativeType.LATEST


def test_blood_pressure_routing_and_entity_recognition():
    """Verify blood pressure routes to [clinical_documents, reports] with entity."""
    # SUP-03: Latest blood pressure reading
    t1 = parse_natural_language_query(
        "What is my latest blood pressure reading?"
    )
    assert t1.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t1.candidate_structured_domains == []
    assert t1.candidate_document_domains == ["clinical_documents", "reports"]
    assert t1.target_entity == "blood pressure"
    assert t1.temporal_constraint.superlative == SuperlativeType.LATEST
    assert t1.temporal_constraint.scope == TemporalScope.ALL

    # SUP-07: First blood pressure measurement
    t2 = parse_natural_language_query(
        "What was my first blood pressure measurement?"
    )
    assert t2.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t2.candidate_structured_domains == []
    assert t2.candidate_document_domains == ["clinical_documents", "reports"]
    assert t2.target_entity == "blood pressure"
    assert t2.temporal_constraint.superlative == SuperlativeType.FIRST
    assert t2.temporal_constraint.scope == TemporalScope.ALL

    # CMP-03: Blood pressure comparison
    t3 = parse_natural_language_query("How did my blood pressure change?")
    assert t3.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t3.candidate_structured_domains == []
    assert t3.candidate_document_domains == ["clinical_documents", "reports"]
    assert t3.target_entity == "blood pressure"
    assert t3.question_intent == "COMPARISON"

    # Semantic separation: "high blood pressure" routes to condition
    t_hbp = parse_natural_language_query("Do I have high blood pressure?")
    assert t_hbp.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "conditions" in t_hbp.candidate_structured_domains
    assert "clinical_documents" in t_hbp.candidate_document_domains
    assert t_hbp.target_entity == "High blood pressure"


def test_timeline_domain_routing():
    """Verify timeline intent queries route according to the locked specification."""
    # TML-01: Health timeline
    t1 = parse_natural_language_query("Show my health timeline")
    assert t1.routing_mode == RoutingMode.STRUCTURED_ONLY
    assert t1.candidate_structured_domains == ["timeline"]
    assert t1.candidate_document_domains == []
    assert t1.target_entity is None
    assert t1.temporal_constraint.scope == TemporalScope.ALL

    # TML-02: Events in 2024
    t2 = parse_natural_language_query("What events happened in 2024?")
    assert t2.routing_mode == RoutingMode.CROSS_DOMAIN
    assert t2.candidate_structured_domains == ["timeline"]
    assert sorted(t2.candidate_document_domains) == sorted(
        ["reports", "labs", "clinical_documents"]
    )
    assert t2.target_entity is None
    assert t2.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t2.temporal_constraint.anchor_year == 2024

    # TML-03: Doctor consultation timeline
    t3 = parse_natural_language_query("When was my doctor consultation?")
    assert t3.routing_mode == RoutingMode.CROSS_DOMAIN
    assert t3.candidate_structured_domains == ["timeline"]
    assert sorted(t3.candidate_document_domains) == sorted(
        ["clinical_documents", "reports"]
    )
    assert t3.target_entity == "consultation"
    assert "prescriptions" not in t3.candidate_document_domains

    # TML-04: Timeline for Asthma
    t4 = parse_natural_language_query("What was my timeline for Asthma?")
    assert t4.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "timeline" in t4.candidate_structured_domains
    assert "conditions" in t4.candidate_structured_domains
    assert t4.candidate_document_domains == ["clinical_documents"]
    assert t4.target_entity == "Asthma"
    assert t4.temporal_constraint.scope == TemporalScope.ALL

    # Document preservation: ordinary doctor query must not route to timeline
    t_doc = parse_natural_language_query("What did my doctor say?")
    assert t_doc.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert "timeline" not in t_doc.candidate_structured_domains
    assert "clinical_documents" in t_doc.candidate_document_domains


def test_comparison_intent_classification():
    """Verify COMPARISON question_intent is set for comparison phrases,
    QUERY otherwise.
    """
    # CMP-01: Cholesterol progression over time
    t1 = parse_natural_language_query(
        "How has my cholesterol changed over time?"
    )
    assert t1.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t1.candidate_document_domains == ["labs"]
    assert t1.target_entity == "Cholesterol"
    assert t1.question_intent == "COMPARISON"

    # CMP-02: Blood test between years
    t2 = parse_natural_language_query(
        "Compare my blood test results between 2023 and 2025"
    )
    assert t2.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t2.candidate_document_domains == ["labs"]
    assert t2.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t2.question_intent == "COMPARISON"

    # CMP-03: Blood pressure change
    t3 = parse_natural_language_query("How did my blood pressure change?")
    assert t3.routing_mode == RoutingMode.DOCUMENT_ONLY
    assert t3.target_entity == "blood pressure"
    assert t3.question_intent == "COMPARISON"

    # CMP-04: Medication dosage comparison over time
    t4 = parse_natural_language_query("Compare my medication dosage over time")
    assert t4.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "medications" in t4.candidate_structured_domains
    assert "prescriptions" in t4.candidate_document_domains
    assert "dosage" in t4.requested_attributes
    assert t4.question_intent == "COMPARISON"

    # Ordinary inquiries remain QUERY
    t_query = parse_natural_language_query("What is my cholesterol?")
    assert t_query.question_intent == "QUERY"

    t_timeline = parse_natural_language_query("Show my health timeline")
    assert t_timeline.question_intent == "QUERY"

    # Negative boundary: "change" without comparison structure remains QUERY
    t_change = parse_natural_language_query("Did my doctor change my medication?")
    assert t_change.question_intent == "QUERY"


def test_relative_time_ambiguity_protection():
    """Verify relative-time expressions do not trigger superlative
    classification.
    """
    # "last year" -> INTERVAL, superlative=None
    t1 = parse_natural_language_query("What was my blood pressure last year?")
    assert t1.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t1.temporal_constraint.superlative is None

    # "last month" -> superlative=None
    t_month = parse_natural_language_query(
        "What was my blood pressure last month?"
    )
    assert t_month.temporal_constraint.superlative is None

    # "past 6 months" -> INTERVAL, superlative=None
    t2 = parse_natural_language_query(
        "What was my cholesterol in the past 6 months?"
    )
    assert t2.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t2.temporal_constraint.superlative is None

    # "last" with clinical entity -> LATEST
    t3 = parse_natural_language_query("What was my last prescription?")
    assert t3.temporal_constraint.superlative == SuperlativeType.LATEST

    t4 = parse_natural_language_query("What was my last test?")
    assert t4.temporal_constraint.superlative == SuperlativeType.LATEST

    t5 = parse_natural_language_query("What was my last blood pressure?")
    assert t5.temporal_constraint.superlative == SuperlativeType.LATEST


def test_regression_and_unroutable_queries():
    """Verify existing M1-M5 behavior is preserved for diabetes and unroutable
    queries.
    """
    # Diabetes regression
    t_diab = parse_natural_language_query("Do I have diabetes?")
    assert t_diab.routing_mode == RoutingMode.CROSS_DOMAIN
    assert "conditions" in t_diab.candidate_structured_domains
    assert t_diab.target_entity == "Diabetes"
    assert t_diab.temporal_constraint.scope == TemporalScope.CURRENT
    assert t_diab.temporal_constraint.superlative is None

    # Unroutable non-medical queries
    t_unr1 = parse_natural_language_query("What is the capital of France?")
    assert t_unr1.routing_mode == RoutingMode.UNROUTABLE
    assert t_unr1.clarification_required is False

    # Unroutable query containing a superlative word
    t_unr2 = parse_natural_language_query("What is the newest phone?")
    assert t_unr2.routing_mode == RoutingMode.UNROUTABLE
    assert t_unr2.clarification_required is False


@patch("app.health.query_understanding.datetime")
def test_superlative_relative_interval_coexistence(mock_datetime):
    """Verify superlative and relative-interval composition under deterministic
    reference date.
    """
    mock_now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now
    ref_year = 2025

    t1 = parse_natural_language_query(
        "What was my last blood pressure reading last year?"
    )
    assert t1.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t1.temporal_constraint.anchor_year == ref_year - 1
    assert t1.temporal_constraint.superlative == SuperlativeType.LATEST

    t2 = parse_natural_language_query(
        "What was my first lab test in the past 30 days?"
    )
    assert t2.temporal_constraint.scope == TemporalScope.INTERVAL
    assert t2.temporal_constraint.superlative == SuperlativeType.FIRST


def test_transitional_target_domain_compatibility():
    """Verify target_domain compatibility accessor behaves correctly on M6
    additions.
    """
    # Timeline-only
    t_timeline = parse_natural_language_query("Show my health timeline")
    assert t_timeline.target_domain == "timeline"

    # Timeline + condition
    t_asthma = parse_natural_language_query("What was my timeline for Asthma?")
    assert t_asthma.target_domain == "conditions"

    # Blood pressure document query
    t_bp = parse_natural_language_query(
        "What is my latest blood pressure reading?"
    )
    assert t_bp.target_domain == "clinical_documents"

