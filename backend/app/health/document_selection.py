import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.db.models import DocumentExtraction, MedicalDocument
from app.schemas.inquiry import InquiryTarget


async def select_document_evidence(
    db: AsyncSession, patient_id: uuid.UUID, target: InquiryTarget
) -> Sequence[MedicalDocument]:
    """
    Deterministically selects candidate document evidence for an inquiry.

    Strict architectural boundaries:
    1. Tenant isolation via patient_id.
    2. Requires extraction_status == COMPLETED and non-empty extracted_text.
    3. Maps InquiryTarget.target_domain to specific MedicalDocument.document_type.
    4. Limits to Top-K = 2 deterministically via document_date and uploaded_at.
    """
    domain = target.target_domain.lower() if target and target.target_domain else None

    # If the domain is None or profile, document selection is not triggered.
    if not domain or domain == "profile":
        return []

    # M3 Locked Document Type Mapping
    allowed_document_types: list[str] = []
    if domain == "labs":
        allowed_document_types = ["lab_report"]
    elif domain == "prescriptions":
        allowed_document_types = ["prescription"]
    elif domain == "reports":
        allowed_document_types = ["diagnostic_report"]
    elif domain == "clinical_documents":
        allowed_document_types = ["discharge_summary", "medical_record", "other"]
    else:
        # Structured domains (medications, conditions, allergies, symptoms, goals)
        # do not trigger document selection.
        return []

    stmt = (
        select(MedicalDocument)
        .options(joinedload(MedicalDocument.document_extraction))
        .join(DocumentExtraction)
        .where(
            MedicalDocument.patient_id == patient_id,
            MedicalDocument.document_type.in_(allowed_document_types),
            DocumentExtraction.extraction_status == "COMPLETED",
            DocumentExtraction.extracted_text.is_not(None),
            DocumentExtraction.extracted_text != "",
        )
        .order_by(
            MedicalDocument.document_date.desc().nulls_last(),
            MedicalDocument.uploaded_at.desc(),
        )
        .limit(2)
    )

    result = await db.execute(stmt)
    return result.unique().scalars().all()
