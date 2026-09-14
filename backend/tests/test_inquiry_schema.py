import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.inquiry import (
    EvidenceStatus,
    HealthInquiryRequest,
    HealthInquiryResponse,
    InquiryCitation,
    InquiryTarget,
    SafetyGuardrailState,
)
from app.schemas.provenance import VerificationState


def test_health_inquiry_request_valid():
    request = HealthInquiryRequest(query="What medications am I taking?")
    assert request.query == "What medications am I taking?"


def test_health_inquiry_request_empty_or_whitespace():
    with pytest.raises(ValidationError) as exc_info:
        HealthInquiryRequest(query="")
    assert "String should have at least 2 characters" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        HealthInquiryRequest(query="   ")
    assert "Query cannot be empty or whitespace only" in str(exc_info.value)


def test_inquiry_target_valid():
    target = InquiryTarget(
        target_domain="medications",
        target_entity="Lisinopril",
        requested_attributes=["dosage", "frequency"],
        temporal_scope="current",
        question_intent="GET_ATTRIBUTE",
    )
    assert target.target_domain == "medications"
    assert target.target_entity == "Lisinopril"
    assert "dosage" in target.requested_attributes
    assert target.temporal_scope == "current"
    assert target.question_intent == "GET_ATTRIBUTE"


def test_inquiry_target_defaults():
    target = InquiryTarget()
    assert target.target_domain is None
    assert target.target_entity is None
    assert target.requested_attributes == []
    assert target.temporal_scope == "all"
    assert target.question_intent == "QUERY"


def test_evidence_status_enum():
    assert EvidenceStatus.SUFFICIENT == "SUFFICIENT"
    assert EvidenceStatus.PARTIALLY_SUFFICIENT == "PARTIALLY_SUFFICIENT"
    assert EvidenceStatus.INSUFFICIENT == "INSUFFICIENT"


def test_inquiry_citation_valid():
    record_id = uuid.uuid4()
    citation = InquiryCitation(
        citation_id=1,
        entity_type="MEDICATION",
        record_id=record_id,
        label="Medication: Lisinopril 10mg",
        verification_state=VerificationState.SOURCE_RECORDED,
    )
    assert citation.citation_id == 1
    assert citation.entity_type == "MEDICATION"
    assert citation.record_id == record_id
    assert citation.label == "Medication: Lisinopril 10mg"
    assert citation.verification_state == VerificationState.SOURCE_RECORDED


def test_inquiry_citation_invalid_uuid():
    with pytest.raises(ValidationError) as exc_info:
        InquiryCitation(
            citation_id=1,
            entity_type="MEDICATION",
            record_id="not-a-uuid",
            label="Medication: Lisinopril 10mg",
            verification_state=VerificationState.SOURCE_RECORDED,
        )
    assert "Input should be a valid UUID" in str(exc_info.value)


def test_inquiry_citation_invalid_verification_state():
    with pytest.raises(ValidationError) as exc_info:
        InquiryCitation(
            citation_id=1,
            entity_type="MEDICATION",
            record_id=uuid.uuid4(),
            label="Medication: Lisinopril 10mg",
            verification_state="INVALID_STATE",
        )
    assert "Input should be" in str(exc_info.value)
    assert "INVALID_STATE" in str(exc_info.value)


def test_safety_guardrail_state_valid():
    state = SafetyGuardrailState(triggered=True, advisory_message="Please seek help.")
    assert state.triggered is True
    assert state.advisory_message == "Please seek help."


def test_health_inquiry_response_serialization():
    record_id = uuid.uuid4()
    generated_time = datetime.now(timezone.utc)

    response = HealthInquiryResponse(
        query="What medications am I taking?",
        answer="You are taking Lisinopril 10mg.",
        evidence_status=EvidenceStatus.SUFFICIENT,
        citations=[
            InquiryCitation(
                citation_id=1,
                entity_type="MEDICATION",
                record_id=record_id,
                label="Medication: Lisinopril 10mg",
                verification_state=VerificationState.SOURCE_RECORDED,
            )
        ],
        safety=SafetyGuardrailState(triggered=False),
        generated_at=generated_time,
    )

    dumped = response.model_dump()
    assert dumped["query"] == "What medications am I taking?"
    assert dumped["answer"] == "You are taking Lisinopril 10mg."
    assert dumped["evidence_status"] == "SUFFICIENT"
    assert dumped["citations"][0]["record_id"] == record_id
    assert dumped["safety"]["triggered"] is False
    assert dumped["generated_at"] == generated_time

    # Also check JSON serialization
    json_dumped = response.model_dump_json()
    assert str(record_id) in json_dumped
    assert "SUFFICIENT" in json_dumped
    assert "MEDICATION" in json_dumped
