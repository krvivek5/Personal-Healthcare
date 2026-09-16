import uuid
from datetime import date

from app.health.inquiry_context import DocumentEvidenceContext, StructuredHealthContext
from app.health.sanitized_context import (
    build_sanitized_context,
    reconcile_reference_tokens,
)
from app.schemas.inquiry import InquiryTarget


def test_document_tokenization_and_sanitization():
    # Setup structured context with documents
    doc_id1 = uuid.uuid4()
    doc_id2 = uuid.uuid4()

    long_excerpt = "A" * 7000
    expected_truncated = "A" * 6000

    docs = [
        DocumentEvidenceContext(
            document_id=doc_id1,
            display_name="Lab Report 1",
            document_type="lab_report",
            document_date=date(2023, 1, 1),
            extracted_excerpt=long_excerpt,
        ),
        DocumentEvidenceContext(
            document_id=doc_id2,
            display_name="Prescription",
            document_type="prescription",
            document_date=date(2023, 1, 2),
            extracted_excerpt="Amoxicillin 500mg",
        ),
    ]

    context = StructuredHealthContext(documents=docs)
    target = InquiryTarget(target_domain="labs")

    sanitized = build_sanitized_context(context, target)

    # Verify DOC-N tokenization
    assert len(sanitized.records) == 2
    assert sanitized.records[0].token == "[DOC-1]"
    assert sanitized.records[1].token == "[DOC-2]"

    # Verify excerpt truncation (6000 chars)
    assert sanitized.records[0].attributes["extracted_excerpt"] == expected_truncated
    assert sanitized.records[1].attributes["extracted_excerpt"] == "Amoxicillin 500mg"

    # Verify safe serialization
    payload = sanitized.to_llm_payload()

    # Storage keys and database IDs should not be in the payload
    # Convert payload to string for easy searching
    payload_str = str(payload)
    assert "document_id" not in payload_str
    assert "storage_key" not in payload_str
    assert str(doc_id1) not in payload_str
    assert str(doc_id2) not in payload_str

    # Verify attributes
    assert payload["records"][0]["attributes"]["display_name"] == "Lab Report 1"
    assert payload["records"][1]["attributes"]["document_type"] == "prescription"

    # Verify reference map points to authoritative UUIDs
    assert sanitized.reference_map["[DOC-1]"] == doc_id1
    assert sanitized.reference_map["[DOC-2]"] == doc_id2


def test_reconcile_reference_tokens_with_docs():
    doc_id = uuid.uuid4()
    rec_id = uuid.uuid4()

    reference_map = {
        "[DOC-1]": doc_id,
        "DOC-1": doc_id,
        "[REC-1]": rec_id,
        "REC-1": rec_id,
    }

    # valid tokens
    cited = ["[DOC-1]", "REC-1"]
    resolved = reconcile_reference_tokens(cited, reference_map)

    assert len(resolved) == 2
    assert doc_id in resolved
    assert rec_id in resolved

    # invalid tokens
    cited_with_invalid = ["[DOC-1]", "[DOC-99]", "UNKNOWN", "[REC-1]"]
    resolved_with_invalid = reconcile_reference_tokens(
        cited_with_invalid, reference_map
    )

    assert len(resolved_with_invalid) == 2
    assert doc_id in resolved_with_invalid
    assert rec_id in resolved_with_invalid

    # Malformed, empty, and unexpected citation tokens fail closed
    malformed_tokens = [
        "",
        "   ",
        "[DOC-]",
        "[DOC-abc]",
        "[DOC--1]",
        "DOC-12345",
        "[MALFORMED]",
        "[]",
        "[   ]",
    ]
    resolved_malformed = reconcile_reference_tokens(malformed_tokens, reference_map)
    assert resolved_malformed == []
