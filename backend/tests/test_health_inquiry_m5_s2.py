"""
Phase 2 — M5 Slice 2: Multi-Domain Document Retrieval Orchestration Tests

Verifies the strict 10-step lifecycle, clarification response contract,
selective context loading, and cross-domain transitional boundary invariants.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Patient
from app.health.evidence_evaluator import EvidenceResult
from app.health.inquiry_context import StructuredHealthContext
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
async def test_ambiguity_zero_database_access(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    AMBIGUOUS_CLARIFY -> short-circuits immediately with clarification prompt.
    Zero patient lookup, zero context loading, zero retrieval, zero LLM.
    """
    mock_parse.return_value = InquiryTarget(
        routing_mode=RoutingMode.AMBIGUOUS_CLARIFY,
        clarification_prompt="Please clarify your request.",
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "How am I doing?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert data["clarification_required"] is True
    assert data["answer"] == "Please clarify your request."

    assert mock_patient.call_count == 0
    assert mock_build_context.call_count == 0
    assert mock_retrieve.call_count == 0
    assert mock_llm_synth.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_unroutable_zero_database_access(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    UNROUTABLE -> short-circuits immediately.
    Zero patient lookup, zero context loading, zero retrieval, zero LLM.
    """
    mock_parse.return_value = InquiryTarget(
        routing_mode=RoutingMode.UNROUTABLE,
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What is the capital of France?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert data["clarification_required"] is False
    assert data["answer"] == "Your query could not be matched to medical records."

    assert mock_patient.call_count == 0
    assert mock_build_context.call_count == 0
    assert mock_retrieve.call_count == 0
    assert mock_llm_synth.synthesize_response.call_count == 0


@pytest.mark.asyncio
async def test_immediate_safety_pre_flight_precedence(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_llm_synth,
):
    """
    Safety triggered -> short-circuits before parse, patient lookup, etc.
    """
    mock_safety.return_value = SafetyGuardrailState(
        triggered=True, advisory_message="Seek emergency care immediately."
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "I am having severe chest pain right now, what should I do?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["safety"]["triggered"] is True
    assert data["answer"] == "Seek emergency care immediately."

    assert mock_parse.call_count == 0
    assert mock_patient.call_count == 0
    assert mock_build_context.call_count == 0
    assert mock_retrieve.call_count == 0


@pytest.mark.asyncio
async def test_document_only_skips_structured_context_loading(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_passage,
    mock_llm_synth,
):
    """
    DOCUMENT_ONLY skips build_inquiry_context and calls retrieve exactly once.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_document_domains=["labs"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What was my creatinine?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200

    # Assert exact calls
    assert mock_patient.call_count == 1
    assert mock_build_context.call_count == 0  # Context skipped
    assert mock_retrieve.call_count == 1

    # Assert candidate domains forwarded unchanged
    mock_retrieve.assert_called_once_with(
        db=mock_retrieve.call_args.kwargs["db"],
        patient_id=PATIENT_ID,
        query_text="What was my creatinine?",
        target_domains=["labs"],
    )


@pytest.mark.asyncio
async def test_multi_domain_document_dispatch(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_passage,
    mock_llm_synth,
):
    """
    Multi-domain document query dispatches candidate domains unchanged in single call.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_document_domains=["clinical_documents", "reports"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What did my doctor note and discharge summary say?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert mock_retrieve.call_count == 1

    # Assert exact candidate list passed
    _, kwargs = mock_retrieve.call_args
    assert kwargs["target_domains"] == ["clinical_documents", "reports"]


@pytest.mark.asyncio
async def test_candidate_collection_non_destructive_invariant():
    """
    Ensure target_domain does not collapse candidate collections.
    """
    target = InquiryTarget(
        candidate_document_domains=["clinical_documents", "reports"],
        routing_mode=RoutingMode.DOCUMENT_ONLY,
    )

    td = target.target_domain
    assert td == "clinical_documents"
    # The collection should not have been truncated
    assert target.candidate_document_domains == ["clinical_documents", "reports"]


@pytest.mark.asyncio
async def test_transitional_cross_domain_structured_preservation(
    async_client: AsyncClient,
    db: AsyncSession,
    mock_safety,
    mock_parse,
    mock_patient,
    mock_build_context,
    mock_retrieve,
    mock_eval_structured,
    mock_llm_synth,
):
    """
    CROSS_DOMAIN routes via STRUCTURED path in S2, not calling retrieval.
    """
    mock_parse.return_value = InquiryTarget(
        candidate_structured_domains=["medications"],
        candidate_document_domains=["prescriptions"],
        routing_mode=RoutingMode.CROSS_DOMAIN,
    )
    user, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        json={"query": "What is the clinic and dosage for my lisinopril?"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert mock_retrieve.call_count == 0
    assert mock_build_context.call_count == 1
    assert mock_eval_structured.call_count == 1
    assert mock_llm_synth.synthesize_response.call_count == 1
