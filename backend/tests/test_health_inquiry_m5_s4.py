"""
Phase 2 — M5 Slice 4: Cross-Domain Evidence Fusion Tests

Verifies the dual-retrieval routing, deterministic citation sequence,
fail-closed behaviors, and fusion logic.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
from app.health.retrieval import RetrievalProviderError
from app.schemas.inquiry import (
    EvidenceStatus,
    InquiryTarget,
    RoutingMode,
    SafetyGuardrailState,
)
from tests.test_health_inquiry_api import create_user_and_token

PATIENT_ID = uuid.uuid4()


@pytest.fixture
def mock_safety():
    with patch("app.api.health_inquiry.evaluate_safety") as mock:
        mock.return_value = SafetyGuardrailState(triggered=False)
        yield mock


@pytest.fixture
def mock_parse():
    with patch("app.api.health_inquiry.parse_natural_language_query") as mock:
        yield mock


@pytest.fixture
def mock_patient():
    with patch(
        "app.api.health_inquiry.get_or_create_patient", new_callable=AsyncMock
    ) as mock:
        patient = Patient(id=PATIENT_ID)
        mock.return_value = patient
        yield mock


@pytest.fixture
def mock_build_context():
    with patch(
        "app.api.health_inquiry.build_inquiry_context", new_callable=AsyncMock
    ) as mock:
        mock.return_value = StructuredHealthContext()
        yield mock


@pytest.fixture
def mock_retrieve():
    with patch(
        "app.api.health_inquiry.retrieve_document_passages", new_callable=AsyncMock
    ) as mock:
        mock.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_eval_passage():
    with patch("app.api.health_inquiry.evaluate_passage_evidence") as mock:
        mock.return_value = EvidenceResult(
            status=EvidenceStatus.SUFFICIENT, qualified_passages=[]
        )
        yield mock


@pytest.fixture
def mock_eval_structured():
    with patch("app.api.health_inquiry.evaluate_evidence") as mock:
        mock.return_value = EvidenceResult(
            status=EvidenceStatus.SUFFICIENT, evidence_directive="Found"
        )
        yield mock


@pytest.fixture
def mock_fuse():
    with patch("app.health.evidence_fusion.fuse_cross_domain_evidence") as mock:
        mock.return_value = EvidenceResult(
            status=EvidenceStatus.SUFFICIENT, evidence_directive="Fused."
        )
        yield mock


@pytest.fixture
def mock_llm_synth():
    with patch("app.api.health_inquiry.get_llm_gateway") as mock_get_gateway:
        mock_provider = AsyncMock()
        from app.core.llm import SynthesisResult

        mock_provider.synthesize_response.return_value = SynthesisResult(
            answer_text="Mocked Answer", cited_record_ids=[], cited_tokens=[]
        )
        mock_get_gateway.return_value = mock_provider
        yield mock_provider


@pytest.mark.asyncio
async def test_cross_domain_success_orchestration(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_structured,
    mock_eval_passage,
    mock_fuse,
    mock_llm_synth,
):
    """
    Verifies that CROSS_DOMAIN invokes both retrieval boundaries and fuses evidence.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes based on notes and records?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert mock_build_context.call_count == 1
    assert mock_retrieve.call_count == 1
    assert mock_eval_structured.call_count == 1
    assert mock_eval_passage.call_count == 1
    assert mock_fuse.call_count == 1
    assert mock_llm_synth.synthesize_response.call_count == 1


@pytest.mark.asyncio
async def test_cross_domain_structured_failure_is_500(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
):
    """
    Verifies that if structured context building fails, the request fails
    closed with 500.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    mock_build_context.side_effect = Exception("Database error")
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 500
    assert mock_build_context.call_count == 1
    assert mock_retrieve.call_count == 0


@pytest.mark.asyncio
async def test_cross_domain_document_failure_is_500(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
):
    """
    Verifies that if document retrieval fails, the request fails closed with 500.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    mock_retrieve.side_effect = RetrievalProviderError("Provider offline")
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 500
    assert mock_build_context.call_count == 1
    assert mock_retrieve.call_count == 1


@pytest.mark.asyncio
async def test_cross_domain_insufficient_evidence_short_circuit(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_structured,
    mock_eval_passage,
    mock_fuse,
    mock_llm_synth,
):
    """
    Verifies that if fuse_cross_domain_evidence returns INSUFFICIENT,
    we short-circuit the LLM.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    mock_fuse.return_value = EvidenceResult(
        status=EvidenceStatus.INSUFFICIENT,
        evidence_directive="Neither domain found it.",
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert response.json()["answer"] == "Neither domain found it."
    assert mock_llm_synth.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_citation_sequence_determinism(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_structured,
    mock_eval_passage,
    mock_fuse,
    mock_llm_synth,
):
    """
    Verifies the server-side citation deduplication and continuous 1-based numbering.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["conditions"],
        candidate_document_domains=["clinical_notes"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )

    # We will simulate the LLM citing the same record multiple times
    rec_id_1 = uuid.uuid4()
    rec_id_2 = uuid.uuid4()

    class DummyCondition:
        def __init__(self, id_val):
            self.id = id_val
            self.name = "Condition"
            self.status = "ACTIVE"
            self.is_chronic = False
            self.started_at = None
            self.ended_at = None
            self.notes = ""
            self.verification_state = "PATIENT_REPORTED"

    mock_build_context.return_value.conditions = [
        DummyCondition(rec_id_1),
        DummyCondition(rec_id_2),
    ]

    from app.core.llm import SynthesisResult

    # The LLM cites rec_id_1 twice and rec_id_2 once.
    mock_llm_synth.synthesize_response.return_value = SynthesisResult(
        answer_text="Mocked Answer",
        cited_record_ids=[rec_id_1, rec_id_2, rec_id_1],
        cited_tokens=["[REC-1]", "[DOC-1]", "[REC-1]"],
    )

    user, token = await create_user_and_token()

    # The citation logic should ignore the duplicate rec_id_1
    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "Do I have diabetes?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    citations = data.get("citations", [])

    # Should be exactly 2 distinct citations
    assert len(citations) == 2
    assert citations[0]["citation_id"] == 1
    assert citations[0]["record_id"] == str(rec_id_1)

    assert citations[1]["citation_id"] == 2
    assert citations[1]["record_id"] == str(rec_id_2)
