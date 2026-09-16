import uuid
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DocumentExtraction, MedicalDocument, Patient
from app.health.document_selection import select_document_evidence
from app.schemas.inquiry import InquiryTarget


@pytest.fixture
async def mock_patient(db: AsyncSession):
    patient_id = uuid.uuid4()
    user_id = uuid.uuid4()
    p = Patient(id=patient_id, user_id=user_id)
    db.add(p)
    await db.commit()
    return p


@pytest.fixture
async def sample_documents(db: AsyncSession, mock_patient):
    """Sets up a diverse set of documents and extractions for the mock patient."""
    base_time = datetime.now()

    # 1. Valid Lab Report
    doc1 = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="lab.pdf",
        display_name="CBC Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/lab.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc1)
    db.add(
        DocumentExtraction(
            document_id=doc1.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="HEMOGLOBIN: 14.2 g/dL",
        )
    )

    # 2. Older Lab Report (should be ordered after doc1)
    doc2 = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="old_lab.pdf",
        display_name="Old Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/old_lab.pdf",
        document_date=date.today() - timedelta(days=30),
        uploaded_at=base_time - timedelta(days=30),
    )
    db.add(doc2)
    db.add(
        DocumentExtraction(
            document_id=doc2.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="HEMOGLOBIN: 13.5 g/dL",
        )
    )

    # 3. Valid Prescription
    doc3 = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="script.pdf",
        display_name="Amoxicillin Rx",
        document_type="prescription",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/script.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc3)
    db.add(
        DocumentExtraction(
            document_id=doc3.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Rx Amoxicillin 500mg BID",
        )
    )

    # 4. Failed Extraction (should be excluded)
    doc4 = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="bad.pdf",
        display_name="Bad Doc",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/bad.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc4)
    db.add(
        DocumentExtraction(
            document_id=doc4.id,
            patient_id=mock_patient.id,
            extraction_status="FAILED",
            extraction_method="test",
            extraction_version="1.0",
            error_message="Corrupted file",
        )
    )

    # doc5 removed because validation prevents COMPLETED with empty text

    # 6. Another Patient's Doc (should be isolated)
    other_patient_id = uuid.uuid4()
    db.add(Patient(id=other_patient_id, user_id=uuid.uuid4()))
    # just create a MedicalDocument to insert it without assigning to unused variable
    db.add(
        MedicalDocument(
            id=uuid.uuid4(),
            patient_id=other_patient_id,
            file_name="other.pdf",
            display_name="Other Lab",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/other.pdf",
            document_date=date.today(),
            uploaded_at=base_time,
        )
    )
    # Note: Foreign key constraints in a real DB would require the other patient
    # to exist, but since this might be a simpler test setup, we just assume it
    # inserts or we mock it. Actually, we should create the other patient to
    # avoid FK violations. We will skip foreign tenant insertion and rely on a
    # separate test for tenant isolation.

    await db.commit()
    return {
        "doc1": doc1.id,
        "doc2": doc2.id,
        "doc3": doc3.id,
        "doc4": doc4.id,
    }


@pytest.mark.asyncio
async def test_select_document_evidence_mapping(
    db: AsyncSession, mock_patient, sample_documents
):
    # Test "labs"
    target = InquiryTarget(target_domain="labs")
    docs = await select_document_evidence(db, mock_patient.id, target)
    assert len(docs) == 2
    assert docs[0].id == sample_documents["doc1"]
    assert docs[1].id == sample_documents["doc2"]

    # Test "prescriptions"
    target = InquiryTarget(target_domain="prescriptions")
    docs = await select_document_evidence(db, mock_patient.id, target)
    assert len(docs) == 1
    assert docs[0].id == sample_documents["doc3"]

    # Test None / profile (should return empty)
    target = InquiryTarget(target_domain=None)
    docs = await select_document_evidence(db, mock_patient.id, target)
    assert len(docs) == 0

    target = InquiryTarget(target_domain="profile")
    docs = await select_document_evidence(db, mock_patient.id, target)
    assert len(docs) == 0


@pytest.mark.asyncio
async def test_select_document_evidence_isolation(
    db: AsyncSession, mock_patient, sample_documents
):
    # Ensure Patient B gets nothing even with valid docs in DB
    other_patient_id = uuid.uuid4()
    target = InquiryTarget(target_domain="labs")
    docs = await select_document_evidence(db, other_patient_id, target)
    assert len(docs) == 0


@pytest.mark.asyncio
async def test_select_document_evidence_top_k_limit(db: AsyncSession, mock_patient):
    # Insert 3 valid lab reports
    base_time = datetime.now()
    for i in range(3):
        doc = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name=f"lab{i}.pdf",
            display_name=f"Lab {i}",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key=f"s3://test/lab{i}.pdf",
            document_date=date.today() - timedelta(days=i),  # i=0 is newest
            uploaded_at=base_time - timedelta(days=i),
        )
        db.add(doc)
        db.add(
            DocumentExtraction(
                document_id=doc.id,
                patient_id=mock_patient.id,
                extraction_status="COMPLETED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="HEMOGLOBIN: 14.2 g/dL",
            )
        )
    await db.commit()

    target = InquiryTarget(target_domain="labs")
    docs = await select_document_evidence(db, mock_patient.id, target)

    # Assert Top-K limit of 2 is enforced and ordered newest first
    assert len(docs) == 2
    assert docs[0].display_name == "Lab 0"
    assert docs[1].display_name == "Lab 1"


@pytest.mark.asyncio
async def test_select_document_evidence_excludes_non_completed_with_text(
    db: AsyncSession, mock_patient
):
    """
    1. A FAILED or UNSUPPORTED extraction with non-empty text is excluded.
    """
    base_time = datetime.now()

    # Drop check constraint to test defense-in-depth query filter directly
    await db.execute(
        text(
            "ALTER TABLE document_extractions "
            "DROP CONSTRAINT IF EXISTS ck_document_extractions_status_content"
        )
    )

    try:
        # FAILED extraction with text
        doc_failed = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name="failed.pdf",
            display_name="Failed Doc",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/failed.pdf",
            document_date=date.today(),
            uploaded_at=base_time,
        )
        db.add(doc_failed)
        # UNSUPPORTED extraction with text
        doc_unsupported = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name="unsupported.pdf",
            display_name="Unsupported Doc",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/unsupported.pdf",
            document_date=date.today(),
            uploaded_at=base_time,
        )
        db.add(doc_unsupported)

        doc_completed = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name="completed.pdf",
            display_name="Completed Doc",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/completed.pdf",
            document_date=date.today() - timedelta(days=1),
            uploaded_at=base_time - timedelta(days=1),
        )
        db.add(doc_completed)
        await db.flush()

        await db.execute(
            insert(DocumentExtraction.__table__).values(
                id=uuid.uuid4(),
                document_id=doc_failed.id,
                patient_id=mock_patient.id,
                extraction_status="FAILED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="Error: extraction failed with partial text",
            )
        )
        await db.execute(
            insert(DocumentExtraction.__table__).values(
                id=uuid.uuid4(),
                document_id=doc_unsupported.id,
                patient_id=mock_patient.id,
                extraction_status="UNSUPPORTED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="Scanned image without font dictionary",
            )
        )
        db.add(
            DocumentExtraction(
                document_id=doc_completed.id,
                patient_id=mock_patient.id,
                extraction_status="COMPLETED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="HEMOGLOBIN: 14.2 g/dL",
            )
        )
        await db.commit()

        target = InquiryTarget(target_domain="labs")
        docs = await select_document_evidence(db, mock_patient.id, target)

        assert len(docs) == 1
        assert docs[0].id == doc_completed.id
    finally:
        await db.execute(
            text(
                "DELETE FROM document_extractions "
                "WHERE extraction_status IN ('FAILED', 'UNSUPPORTED') "
                "AND extracted_text IS NOT NULL AND length(trim(extracted_text)) > 0"
            )
        )
        await db.execute(
            text(
                "ALTER TABLE document_extractions "
                "ADD CONSTRAINT ck_document_extractions_status_content "
                "CHECK ("
                "(extraction_status = 'COMPLETED' "
                "AND extracted_text IS NOT NULL "
                "AND length(trim(extracted_text)) > 0) "
                "OR (extraction_status IN ('FAILED', 'UNSUPPORTED') "
                "AND (extracted_text IS NULL OR length(trim(extracted_text)) = 0))"
                ")"
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_select_document_evidence_excludes_completed_with_empty_text(
    db: AsyncSession, mock_patient
):
    """
    2. A COMPLETED extraction with empty extracted_text is excluded.
    """
    base_time = datetime.now()

    # Drop check constraint to test defense-in-depth query filter directly
    await db.execute(
        text(
            "ALTER TABLE document_extractions "
            "DROP CONSTRAINT IF EXISTS ck_document_extractions_status_content"
        )
    )

    try:
        doc_empty = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name="empty.pdf",
            display_name="Empty Doc",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/empty.pdf",
            document_date=date.today(),
            uploaded_at=base_time,
        )
        db.add(doc_empty)

        doc_valid = MedicalDocument(
            id=uuid.uuid4(),
            patient_id=mock_patient.id,
            file_name="valid.pdf",
            display_name="Valid Doc",
            document_type="lab_report",
            content_type="application/pdf",
            file_size_bytes=1000,
            storage_key="s3://test/valid.pdf",
            document_date=date.today() - timedelta(days=1),
            uploaded_at=base_time - timedelta(days=1),
        )
        db.add(doc_valid)
        await db.flush()

        await db.execute(
            insert(DocumentExtraction.__table__).values(
                id=uuid.uuid4(),
                document_id=doc_empty.id,
                patient_id=mock_patient.id,
                extraction_status="COMPLETED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="",
            )
        )
        db.add(
            DocumentExtraction(
                document_id=doc_valid.id,
                patient_id=mock_patient.id,
                extraction_status="COMPLETED",
                extraction_method="test",
                extraction_version="1.0",
                extracted_text="Valid content",
            )
        )
        await db.commit()

        target = InquiryTarget(target_domain="labs")
        docs = await select_document_evidence(db, mock_patient.id, target)

        assert len(docs) == 1
        assert docs[0].id == doc_valid.id
    finally:
        await db.execute(
            text(
                "DELETE FROM document_extractions "
                "WHERE extraction_status = 'COMPLETED' "
                "AND (extracted_text IS NULL OR length(trim(extracted_text)) = 0)"
            )
        )
        await db.execute(
            text(
                "ALTER TABLE document_extractions "
                "ADD CONSTRAINT ck_document_extractions_status_content "
                "CHECK ("
                "(extraction_status = 'COMPLETED' "
                "AND extracted_text IS NOT NULL "
                "AND length(trim(extracted_text)) > 0) "
                "OR (extraction_status IN ('FAILED', 'UNSUPPORTED') "
                "AND (extracted_text IS NULL OR length(trim(extracted_text)) = 0))"
                ")"
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_select_document_evidence_reports_mapping(db: AsyncSession, mock_patient):
    """3. target_domain='reports' selects only document_type='diagnostic_report'."""
    base_time = datetime.now()

    doc_diag = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="mri.pdf",
        display_name="MRI Brain",
        document_type="diagnostic_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/mri.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc_diag)
    db.add(
        DocumentExtraction(
            document_id=doc_diag.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="MRI Brain Normal",
        )
    )

    doc_lab = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="cbc.pdf",
        display_name="CBC Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/cbc.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc_lab)
    db.add(
        DocumentExtraction(
            document_id=doc_lab.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="CBC Normal",
        )
    )
    await db.commit()

    target = InquiryTarget(target_domain="reports")
    docs = await select_document_evidence(db, mock_patient.id, target)

    assert len(docs) == 1
    assert docs[0].id == doc_diag.id
    assert docs[0].document_type == "diagnostic_report"


@pytest.mark.asyncio
async def test_select_document_evidence_clinical_documents_mapping(
    db: AsyncSession, mock_patient
):
    """
    4. target_domain='clinical_documents' selects discharge, record, other.
    """
    base_time = datetime.now()

    # 1. discharge_summary
    doc_discharge = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="discharge.pdf",
        display_name="Discharge Summary",
        document_type="discharge_summary",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/discharge.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc_discharge)
    db.add(
        DocumentExtraction(
            document_id=doc_discharge.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Discharge Instructions",
        )
    )

    # 2. medical_record
    doc_record = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="record.pdf",
        display_name="Medical Record",
        document_type="medical_record",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/record.pdf",
        document_date=date.today() - timedelta(days=1),
        uploaded_at=base_time - timedelta(days=1),
    )
    db.add(doc_record)
    db.add(
        DocumentExtraction(
            document_id=doc_record.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Clinical progress record",
        )
    )

    # 3. other
    doc_other = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="other.pdf",
        display_name="Other Clinical Note",
        document_type="other",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/other.pdf",
        document_date=date.today() - timedelta(days=2),
        uploaded_at=base_time - timedelta(days=2),
    )
    db.add(doc_other)
    db.add(
        DocumentExtraction(
            document_id=doc_other.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Other clinical note text",
        )
    )

    # 4. lab_report (should be excluded)
    doc_lab = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="lab.pdf",
        display_name="Lab Report",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/lab.pdf",
        document_date=date.today(),
        uploaded_at=base_time,
    )
    db.add(doc_lab)
    db.add(
        DocumentExtraction(
            document_id=doc_lab.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Lab text",
        )
    )
    await db.commit()

    target = InquiryTarget(target_domain="clinical_documents")
    docs = await select_document_evidence(db, mock_patient.id, target)

    # Top-K=2 selects 2 most recent: discharge_summary and medical_record
    assert len(docs) == 2
    assert docs[0].id == doc_discharge.id
    assert docs[1].id == doc_record.id
    assert docs[0].document_type == "discharge_summary"
    assert docs[1].document_type == "medical_record"


@pytest.mark.asyncio
async def test_select_document_evidence_null_document_date_ordering(
    db: AsyncSession, mock_patient
):
    """5. document_date=NULL is ordered after real dates, uploaded_at breaks ties."""
    base_time = datetime.now()

    # 1. Dated document (older upload, but has real date -> must come first)
    doc_dated = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="dated.pdf",
        display_name="Dated Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/dated.pdf",
        document_date=date.today() - timedelta(days=10),
        uploaded_at=base_time - timedelta(hours=3),
    )
    db.add(doc_dated)
    db.add(
        DocumentExtraction(
            document_id=doc_dated.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Dated lab report",
        )
    )

    # 2. Undated document with newer upload
    doc_undated_newer = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="undated_newer.pdf",
        display_name="Undated Newer Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/undated_newer.pdf",
        document_date=None,
        uploaded_at=base_time,
    )
    db.add(doc_undated_newer)
    db.add(
        DocumentExtraction(
            document_id=doc_undated_newer.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Undated newer report",
        )
    )

    # 3. Undated document with older upload (should be ranked 3rd and cut by Top-K=2)
    doc_undated_older = MedicalDocument(
        id=uuid.uuid4(),
        patient_id=mock_patient.id,
        file_name="undated_older.pdf",
        display_name="Undated Older Lab",
        document_type="lab_report",
        content_type="application/pdf",
        file_size_bytes=1000,
        storage_key="s3://test/undated_older.pdf",
        document_date=None,
        uploaded_at=base_time - timedelta(hours=5),
    )
    db.add(doc_undated_older)
    db.add(
        DocumentExtraction(
            document_id=doc_undated_older.id,
            patient_id=mock_patient.id,
            extraction_status="COMPLETED",
            extraction_method="test",
            extraction_version="1.0",
            extracted_text="Undated older report",
        )
    )
    await db.commit()

    target = InquiryTarget(target_domain="labs")
    docs = await select_document_evidence(db, mock_patient.id, target)

    assert len(docs) == 2
    # NULLS LAST ensures doc_dated comes before doc_undated_newer
    assert docs[0].id == doc_dated.id
    # Between undated docs, uploaded_at DESC selects doc_undated_newer
    assert docs[1].id == doc_undated_newer.id


@pytest.mark.asyncio
async def test_select_document_evidence_structured_domains_return_empty(
    db: AsyncSession, mock_patient, sample_documents
):
    """Structured domains must never select documents."""
    for domain in [
        "medications",
        "conditions",
        "allergies",
        "symptoms",
        "goals",
        "unknown_domain",
    ]:
        target = InquiryTarget(target_domain=domain)
        docs = await select_document_evidence(db, mock_patient.id, target)
        assert docs == []
