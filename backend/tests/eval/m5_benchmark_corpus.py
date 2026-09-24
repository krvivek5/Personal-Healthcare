from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.inquiry import RoutingMode, TemporalScope


class BenchmarkTestCase(BaseModel):
    case_id: str  # Unique ID across the 54 benchmark corpus cases
    category: str  # One of the 9 locked categories
    query: str  # Exact input natural-language query string
    expected_routing_mode: RoutingMode  # Expected router classification
    expected_structured_domains: list[str] = Field(default_factory=list)
    expected_document_domains: list[str] = Field(default_factory=list)
    expected_target_entity: Optional[str] = None
    expected_attributes: list[str] = Field(default_factory=list)
    expected_temporal_scope: TemporalScope = TemporalScope.ALL
    expected_anchor_year: Optional[int] = None
    expected_start_date: Optional[date] = None
    expected_end_date: Optional[date] = None
    expected_clarification_required: bool = False
    is_safety_trigger: bool = False


M5_BENCHMARK_CORPUS: tuple[BenchmarkTestCase, ...] = (
    # -------------------------------------------------------------------------
    # Category 1: Explicit-Domain Queries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="EXP-01",
        category="Explicit-Domain",
        query="What medications am I taking?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions"],
        # Confirmed: Router does not extract attributes unless explicitly present
        expected_attributes=[],
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="EXP-02",
        category="Explicit-Domain",
        query="Show me my diagnosed conditions.",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["clinical_documents"],
        # S1 Section 6.1 contract: "diagnosed" maps to HISTORICAL
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    BenchmarkTestCase(
        case_id="EXP-03",
        category="Explicit-Domain",
        query="What are my active allergies?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["allergies"],
        expected_document_domains=["clinical_documents"],
        expected_attributes=[
            "status"
        ],  # S3 canonical attribute vocabulary: "active" maps to "status"
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="EXP-04",
        category="Explicit-Domain",
        query="What symptoms have I logged?",
        expected_routing_mode=RoutingMode.STRUCTURED_ONLY,
        expected_structured_domains=["symptoms"],
        expected_document_domains=[],
        # S1 Section 6.1 contract: "have" maps to CURRENT
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="EXP-05",
        category="Explicit-Domain",
        query="What are my health goals?",
        expected_routing_mode=RoutingMode.STRUCTURED_ONLY,
        expected_structured_domains=["goals"],
        expected_document_domains=[],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="EXP-06",
        category="Explicit-Domain",
        query="What lab reports have been uploaded?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=[
            "clinical_documents",
            "labs",
            "reports",
        ],  # Union of "lab" (labs) and "reports" (reports, clinical_documents)
        # S1 Section 6.1 contract: "have" maps to CURRENT
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    # -------------------------------------------------------------------------
    # Category 2: Implicit-Document Queries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="IMP-01",
        category="Implicit-Document",
        query="What did my chest x-ray show?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["reports", "clinical_documents"],
        # S3 Section 7: eliminated generic document-keyword -> target_entity fallback
        expected_target_entity=None,
    ),
    BenchmarkTestCase(
        case_id="IMP-02",
        category="Implicit-Document",
        query="What were the findings on my brain MRI?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["reports", "clinical_documents"],
        # S3 Section 7: eliminated generic document-keyword -> target_entity fallback
        expected_target_entity=None,
    ),
    BenchmarkTestCase(
        case_id="IMP-03",
        category="Implicit-Document",
        query="What did the ultrasound reveal?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["reports", "clinical_documents"],
        # S3 Section 7: eliminated generic document-keyword -> target_entity fallback
        expected_target_entity=None,
    ),
    BenchmarkTestCase(
        case_id="IMP-04",
        category="Implicit-Document",
        query="What were my biopsy results?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["reports", "clinical_documents"],
        # S3 Section 7: eliminated generic document-keyword -> target_entity fallback
        expected_target_entity=None,
    ),
    BenchmarkTestCase(
        case_id="IMP-05",
        category="Implicit-Document",
        query="What did my doctor say at the last consultation?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=[
            "clinical_documents",
            "prescriptions",
            "reports",
        ],  # Union of consultation + provider anchors
        expected_attributes=["consultation_notes"],
    ),
    BenchmarkTestCase(
        case_id="IMP-06",
        category="Implicit-Document",
        query="What are my discharge instructions?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["clinical_documents", "reports"],
        expected_attributes=["consultation_notes"],
    ),
    # -------------------------------------------------------------------------
    # Category 3: Provider / Physician Queries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="PRV-01",
        category="Provider-Physician",
        query="What is my physician name?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["prescriptions", "clinical_documents"],
        expected_attributes=["physician_name"],
    ),
    BenchmarkTestCase(
        case_id="PRV-02",
        category="Provider-Physician",
        query="Who is my prescribing doctor?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["prescriptions", "clinical_documents"],
        expected_attributes=["physician_name"],
    ),
    BenchmarkTestCase(
        case_id="PRV-03",
        category="Provider-Physician",
        query="What is my doctor's phone number?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["prescriptions", "clinical_documents"],
        expected_attributes=["contact_number"],
    ),
    BenchmarkTestCase(
        case_id="PRV-04",
        category="Provider-Physician",
        query="What clinic did I visit?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["clinical_documents", "reports"],
        expected_attributes=["clinic"],
    ),
    BenchmarkTestCase(
        case_id="PRV-05",
        category="Provider-Physician",
        query="Who signed my prescription?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions", "clinical_documents"],
        expected_attributes=["physician_name"],
    ),
    BenchmarkTestCase(
        case_id="PRV-06",
        category="Provider-Physician",
        query="What hospital was I admitted to?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["clinical_documents", "reports"],
        expected_attributes=["clinic"],
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    # -------------------------------------------------------------------------
    # Category 4: Structured Entity Synonyms (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="SYN-01",
        category="Entity-Synonyms",
        query="Am I taking Metformin?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions"],
        expected_target_entity="Metformin",
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="SYN-02",
        category="Entity-Synonyms",
        query="What is my dosage of Atorvastatin?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions"],
        expected_target_entity="Atorvastatin",
        expected_attributes=["dosage"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="SYN-03",
        category="Entity-Synonyms",
        query="Do I have Hypertension?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["clinical_documents"],
        expected_target_entity="Hypertension",
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="SYN-04",
        category="Entity-Synonyms",
        query="Was I diagnosed with Type 2 Diabetes?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["clinical_documents"],
        expected_target_entity="Diabetes",  # Entity extraction resolves to "Diabetes"
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    BenchmarkTestCase(
        case_id="SYN-05",
        category="Entity-Synonyms",
        query="Do I have an allergy to Penicillin?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["allergies"],
        expected_document_domains=["clinical_documents"],
        expected_target_entity="Penicillin",
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="SYN-06",
        category="Entity-Synonyms",
        query="Do I have a Peanut allergy?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["allergies"],
        expected_document_domains=["clinical_documents"],
        expected_target_entity="Peanut",
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    # -------------------------------------------------------------------------
    # Category 5: Cross-Domain Inquiries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="CRS-01",
        category="Cross-Domain",
        query="Who prescribed my Lisinopril and at what dose?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions", "clinical_documents"],
        expected_target_entity="Lisinopril",
        expected_attributes=["dosage", "physician_name"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="CRS-02",
        category="Cross-Domain",
        query="Do I have asthma and what did my chest report say?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["reports", "clinical_documents"],
        expected_target_entity="Asthma",
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="CRS-03",
        category="Cross-Domain",
        query="What medications am I taking and what were the doctor notes?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["clinical_documents", "reports", "prescriptions"],
        expected_attributes=["consultation_notes"],
        expected_temporal_scope=TemporalScope.CURRENT,
    ),
    BenchmarkTestCase(
        case_id="CRS-04",
        category="Cross-Domain",
        query="What did the lab say about my diabetes?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["labs", "clinical_documents"],
        expected_target_entity="Diabetes",
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="CRS-05",
        category="Cross-Domain",
        query="Show my medical history and recent records.",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions", "medications"],
        expected_document_domains=[
            "clinical_documents",
            "reports",
            "prescriptions",
            "labs",
        ],
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    BenchmarkTestCase(
        case_id="CRS-06",
        category="Cross-Domain",
        query="Who prescribed my medication and what clinic was it?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions", "clinical_documents", "reports"],
        expected_attributes=["clinic", "physician_name"],
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    # -------------------------------------------------------------------------
    # Category 6: Attribute-Only Queries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="ATT-01",
        category="Attribute-Only",
        query="What is my dosage?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["prescriptions"],
        expected_attributes=["dosage"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="ATT-02",
        category="Attribute-Only",
        query="What is my blood group?",
        expected_routing_mode=RoutingMode.STRUCTURED_ONLY,
        expected_structured_domains=["profile"],
        expected_document_domains=[],
        expected_attributes=["blood_group"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="ATT-03",
        category="Attribute-Only",
        query="How often should I take my prescription?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["prescriptions"],
        expected_attributes=["frequency"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="ATT-04",
        category="Attribute-Only",
        query="What is the clinic contact number?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["clinical_documents", "reports"],
        expected_attributes=["clinic", "contact_number"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="ATT-05",
        category="Attribute-Only",
        query="What is the medication frequency?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions"],
        expected_attributes=["frequency"],
        expected_temporal_scope=TemporalScope.ALL,
    ),
    BenchmarkTestCase(
        case_id="ATT-06",
        category="Attribute-Only",
        query="What clinic was listed?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["clinical_documents", "reports"],
        expected_attributes=["clinic"],
        expected_temporal_scope=TemporalScope.HISTORICAL,
    ),
    # -------------------------------------------------------------------------
    # Category 7: True Ambiguity & Unroutable Queries (6 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="AMB-01",
        category="True-Ambiguity",
        query="How am I doing?",
        expected_routing_mode=RoutingMode.AMBIGUOUS_CLARIFY,
        expected_clarification_required=True,
    ),
    BenchmarkTestCase(
        case_id="AMB-02",
        category="True-Ambiguity",
        query="Tell me something useful.",
        expected_routing_mode=RoutingMode.AMBIGUOUS_CLARIFY,
        expected_clarification_required=True,
    ),
    BenchmarkTestCase(
        case_id="AMB-03",
        category="True-Ambiguity",
        query="What should I know?",
        expected_routing_mode=RoutingMode.AMBIGUOUS_CLARIFY,
        expected_clarification_required=True,
    ),
    BenchmarkTestCase(
        case_id="AMB-04",
        category="True-Ambiguity",
        query="Can you help me?",
        expected_routing_mode=RoutingMode.AMBIGUOUS_CLARIFY,
        expected_clarification_required=True,
    ),
    BenchmarkTestCase(
        case_id="UNR-01",
        category="Unroutable",
        query="What is the capital of France?",
        expected_routing_mode=RoutingMode.UNROUTABLE,
        expected_clarification_required=False,
    ),
    BenchmarkTestCase(
        case_id="UNR-02",
        category="Unroutable",
        query="How do I repair my car engine?",
        expected_routing_mode=RoutingMode.UNROUTABLE,
        expected_clarification_required=False,
    ),
    # -------------------------------------------------------------------------
    # Category 8: Temporal Interval Queries (8 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="TMP-01",
        category="Temporal-Interval",
        query="What was my cholesterol in 2024?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["labs"],
        expected_target_entity="Cholesterol",
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_anchor_year=2024,
        expected_start_date=date(2024, 1, 1),
        expected_end_date=date(2024, 12, 31),
    ),
    BenchmarkTestCase(
        case_id="TMP-02",
        category="Temporal-Interval",
        query="What medications was I taking in 2023?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["medications"],
        expected_document_domains=["prescriptions"],
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_anchor_year=2023,
        expected_start_date=date(2023, 1, 1),
        expected_end_date=date(2023, 12, 31),
    ),
    BenchmarkTestCase(
        case_id="TMP-03",
        category="Temporal-Interval",
        query="What was my blood work last year?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["labs"],
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_anchor_year=2025,  # Ref date: 2026-09-24 -> ref_year - 1 = 2025
        expected_start_date=date(2025, 1, 1),
        expected_end_date=date(2025, 12, 31),
    ),
    BenchmarkTestCase(
        case_id="TMP-04",
        category="Temporal-Interval",
        query="Show my lab results from March 2024.",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["labs"],
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_anchor_year=2024,
        expected_start_date=date(2024, 3, 1),
        expected_end_date=date(2024, 3, 31),
    ),
    BenchmarkTestCase(
        case_id="TMP-05",
        category="Temporal-Interval",
        query="What was my cholesterol on 2024-06-15?",
        expected_routing_mode=RoutingMode.DOCUMENT_ONLY,
        expected_structured_domains=[],
        expected_document_domains=["labs"],
        expected_target_entity="Cholesterol",
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_anchor_year=2024,
        expected_start_date=date(2024, 6, 15),
        expected_end_date=date(2024, 6, 15),
    ),
    BenchmarkTestCase(
        case_id="TMP-06",
        category="Temporal-Interval",
        query="Did I have hypertension between 2021 and 2023?",
        expected_routing_mode=RoutingMode.CROSS_DOMAIN,
        expected_structured_domains=["conditions"],
        expected_document_domains=["clinical_documents"],
        expected_target_entity="Hypertension",
        expected_temporal_scope=TemporalScope.INTERVAL,
        expected_start_date=date(2021, 1, 1),
        expected_end_date=date(2023, 12, 31),
    ),
    BenchmarkTestCase(
        case_id="TMP-07",
        category="Temporal-Interval",
        query="What was my blood test on February 30, 2024?",
        # Expected fail-closed impossible date
        expected_routing_mode=RoutingMode.UNROUTABLE,
        expected_clarification_required=False,
    ),
    BenchmarkTestCase(
        case_id="TMP-08",
        category="Temporal-Interval",
        query="What were my meds between 2024 and 2021?",
        # Expected fail-closed inverted interval
        expected_routing_mode=RoutingMode.UNROUTABLE,
        expected_clarification_required=False,
    ),
    # -------------------------------------------------------------------------
    # Category 9: Safety Precedence Invariants (4 cases)
    # -------------------------------------------------------------------------
    BenchmarkTestCase(
        case_id="SAF-01",
        category="Safety-Precedence",
        query="I have severe crushing chest pain right now.",
        # In API lifecycle, short-circuits at evaluate_safety
        expected_routing_mode=RoutingMode.UNROUTABLE,
        is_safety_trigger=True,
    ),
    BenchmarkTestCase(
        case_id="SAF-02",
        category="Safety-Precedence",
        query="I have sudden weakness and facial drooping.",
        expected_routing_mode=RoutingMode.UNROUTABLE,
        is_safety_trigger=True,
    ),
    BenchmarkTestCase(
        case_id="SAF-03",
        category="Safety-Precedence",
        query="I can't breathe and am gasping for air.",
        expected_routing_mode=RoutingMode.UNROUTABLE,
        is_safety_trigger=True,
    ),
    BenchmarkTestCase(
        case_id="SAF-04",
        category="Safety-Precedence",
        query="I am having an allergic reaction and my throat is closing.",
        expected_routing_mode=RoutingMode.UNROUTABLE,
        is_safety_trigger=True,
    ),
)


# -----------------------------------------------------------------------------
# Corpus Sub-Population Inspection Helpers
# -----------------------------------------------------------------------------
def get_case_by_id(case_id: str) -> Optional[BenchmarkTestCase]:
    """Retrieve a benchmark case by its unique ID."""
    for case in M5_BENCHMARK_CORPUS:
        if case.case_id == case_id:
            return case
    return None


def get_cases_by_category(category: str) -> tuple[BenchmarkTestCase, ...]:
    """Retrieve all benchmark cases belonging to a category as a fixed tuple."""
    return tuple(case for case in M5_BENCHMARK_CORPUS if case.category == category)


def get_parser_benchmark_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve the 50 non-safety parser benchmark cases."""
    return tuple(case for case in M5_BENCHMARK_CORPUS if not case.is_safety_trigger)


def get_safety_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve the 4 safety precedence trigger cases."""
    return tuple(case for case in M5_BENCHMARK_CORPUS if case.is_safety_trigger)


def get_normal_routable_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve 42 normal routable cases (excl. safety, ambiguous, unroutable)."""
    return tuple(
        case
        for case in M5_BENCHMARK_CORPUS
        if not case.is_safety_trigger
        and not case.expected_clarification_required
        and case.expected_routing_mode != RoutingMode.UNROUTABLE
    )


def get_ambiguous_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve the 4 true ambiguous cases requiring clarification."""
    return tuple(
        case for case in M5_BENCHMARK_CORPUS if case.expected_clarification_required
    )


def get_non_ambiguous_parser_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve 46 non-ambiguous parser cases (excl. safety and ambiguous)."""
    return tuple(
        case
        for case in M5_BENCHMARK_CORPUS
        if not case.is_safety_trigger and not case.expected_clarification_required
    )


def get_valid_temporal_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve the 6 valid temporal normalization cases (TMP-01..06)."""
    return tuple(
        case
        for case in M5_BENCHMARK_CORPUS
        if case.category == "Temporal-Interval"
        and case.expected_routing_mode != RoutingMode.UNROUTABLE
    )


def get_invalid_temporal_cases() -> tuple[BenchmarkTestCase, ...]:
    """Retrieve the 2 invalid temporal fail-closed cases (TMP-07..08)."""
    return tuple(
        case
        for case in M5_BENCHMARK_CORPUS
        if case.category == "Temporal-Interval"
        and case.expected_routing_mode == RoutingMode.UNROUTABLE
    )
