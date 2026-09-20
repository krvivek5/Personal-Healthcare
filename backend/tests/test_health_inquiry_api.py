import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

from app.api.health_inquiry import get_llm_provider
from app.core.llm import SynthesisResult
from app.db.base import async_session_factory
from app.db.models import DocumentExtraction, MedicalDocument
from app.health.patient import get_or_create_patient
from app.health.safety_guardrails import SAFETY_ADVISORY
from app.main import app
from app.schemas.inquiry import EvidenceStatus
from tests.test_auth import create_test_token

pytestmark = pytest.mark.asyncio


async def create_user_and_token():
    user_id = str(uuid.uuid4())
    token = create_test_token(user_id=user_id)
    return user_id, token


async def setup_patient_data(async_client: AsyncClient, token: str) -> str:
    # Create profile
    await async_client.put(
        "/api/v1/health-profile",
        headers={"Authorization": f"Bearer {token}"},
        json={"blood_group": "O+"},
    )
    # Create condition "Asthma"
    res = await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Asthma", "status": "active", "is_chronic": True},
    )
    return res.json()["id"]


async def test_health_inquiry_sufficient_evidence(async_client: AsyncClient):
    _, token = await create_user_and_token()
    condition_id = await setup_patient_data(async_client, token)

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "Do I have asthma?"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.SUFFICIENT
    assert "confirm" in data["answer"].lower()
    assert len(data["citations"]) == 1
    assert data["citations"][0]["record_id"] == condition_id
    assert data["citations"][0]["entity_type"] == "CONDITION"
    assert data["citations"][0]["label"] == "Asthma"


async def test_unauthenticated_request(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/health-inquiry", json={"query": "Do I have asthma?"}
    )
    assert response.status_code == 401


async def test_patient_context_isolation(async_client: AsyncClient):
    _, token_a = await create_user_and_token()
    await setup_patient_data(async_client, token_a)

    _, token_b = await create_user_and_token()

    # User B queries about asthma, should be insufficient since they have no records
    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"query": "Do I have asthma?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert len(data["citations"]) == 0


async def test_partial_evidence_response(async_client: AsyncClient):
    _, token = await create_user_and_token()
    await setup_patient_data(async_client, token)

    # Create medication with dosage but no clinic
    await async_client.post(
        "/api/v1/medications",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Lisinopril", "status": "active", "dosage": "10mg"},
    )

    # Ask for clinic (missing attribute) and dosage (present attribute)
    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "What is the clinic and dosage for my lisinopril?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.PARTIALLY_SUFFICIENT
    # Based on MockLLMProvider behavior, partial returns the evidence_directive directly
    ans = data["answer"].lower()
    assert "partially available" in ans or "not recorded" in ans


async def test_insufficient_evidence_response(async_client: AsyncClient):
    _, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "What is my blood type?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT
    assert len(data["citations"]) == 0


async def test_current_vs_historical_query(async_client: AsyncClient):
    _, token = await create_user_and_token()
    await async_client.post(
        "/api/v1/conditions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Asthma",
            "status": "resolved",
            "is_chronic": False,
            "ended_at": "2026-01-01",
        },
    )

    # Query current conditions
    res_current = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "Do I currently have asthma?"},
    )
    assert res_current.json()["evidence_status"] == EvidenceStatus.INSUFFICIENT

    # Query historical
    res_past = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "Was I diagnosed with asthma?"},
    )
    assert res_past.json()["evidence_status"] == EvidenceStatus.SUFFICIENT


async def test_invalid_foreign_citation_removed(async_client: AsyncClient):
    _, token = await create_user_and_token()

    class EvilMockLLMProvider:
        async def synthesize_response(
            self, query, target, context, evidence, safety_state
        ) -> SynthesisResult:
            return SynthesisResult(
                answer_text="Here is a fake citation.",
                cited_record_ids=[uuid.uuid4()],  # foreign ID
            )

    app.dependency_overrides[get_llm_provider] = lambda: EvilMockLLMProvider()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "Do I have asthma?"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert len(data["citations"]) == 0  # Fake citation should be filtered


async def test_safety_triggered_inquiry(async_client: AsyncClient):
    _, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "I have severe chest pain right now."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["safety"]["triggered"] is True
    assert data["answer"] == SAFETY_ADVISORY
    assert len(data["citations"]) == 0


async def test_empty_structured_context(async_client: AsyncClient):
    _, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "What conditions do I have?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["evidence_status"] == EvidenceStatus.INSUFFICIENT


async def test_malformed_query_validation(async_client: AsyncClient):
    _, token = await create_user_and_token()

    response = await async_client.post(
        "/api/v1/health-inquiry",
        headers={"Authorization": f"Bearer {token}"},
        json={"query": "   "},
    )
    assert response.status_code == 422


async def seed_patient_document(
    user_id: str,
    display_name: str,
    document_type: str,
    document_date: date | None,
    extracted_text: str,
    extraction_status: str = "COMPLETED",
    uploaded_at: datetime | None = None,
) -> uuid.UUID:
    async with async_session_factory() as session:
        patient = await get_or_create_patient(session, uuid.UUID(user_id))
        doc = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=patient.id,
            file_name=f"{display_name.lower().replace(' ', '_')}.pdf",
            display_name=display_name,
            document_type=document_type,
            content_type="application/pdf",
            file_size_bytes=1024,
            storage_key=f"documents/{patient.id}/{uuid.uuid4()}.pdf",
            document_date=document_date,
            uploaded_at=uploaded_at or datetime.now(timezone.utc),
        )
        session.add(doc)
        extraction = DocumentExtraction(
            id=uuid.uuid4(),
            document_id=doc.id,
            patient_id=patient.id,
            extraction_status=extraction_status,
            extraction_method="test",
            extraction_version="1.0.0",
            extracted_text=extracted_text,
            extracted_at=datetime.now(timezone.utc),
        )
        session.add(extraction)
        await session.commit()
        return doc.id
