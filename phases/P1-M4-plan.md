# Milestone 4 — Medical Documents

Upload, store, list, retrieve, and delete medical documents with strict user isolation. The original document is preserved as source material in S3-compatible object storage; metadata lives in PostgreSQL.

## Resolved Design Decisions

| # | Decision | Resolution |
|---|---|---|
| 1 | Storage backend | S3-compatible (MinIO in local dev via Docker Compose). Uses existing `S3_*` config settings. |
| 2 | File size limit | **20 MB** per upload. Accepted types: `application/pdf`, `image/jpeg`, `image/png`. |
| 3 | Delete strategy | **Hard delete** (S3 object + DB row). Matches existing entity patterns. |
| 4 | `document_date` | Included as optional. Separate from `uploaded_at`. Useful for M5 timeline. |
| 5 | Download approach | **Authenticated backend streaming** — no presigned URLs. |
| 6 | Storage key format | `documents/{patient_id}/{uuid}` — original filename stored only in DB metadata. |
| 7 | Document types | Strictly constrained to: `lab_report`, `prescription`, `diagnostic_report`, `discharge_summary`, `medical_record`, `other`. |

---

## Proposed Changes

Changes are grouped by layer, dependency order (Infrastructure → DB → service → API → frontend).

---

### Infrastructure — Local Object Storage

#### [MODIFY] [docker-compose.yml](file:///d:/Personal%20Projects/Personal%20HealthCare/docker-compose.yml)

Add a MinIO service for local S3-compatible object storage:

```yaml
  minio:
    image: minio/minio:RELEASE.2024-03-07T00-43-48Z
    container_name: personal_health_minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # Web console
    volumes:
      - minio_data:/data
```

Add `minio_data` to the `volumes:` block.

Use a verified readiness healthcheck supported by the selected pinned MinIO image. The concrete command must be verified during implementation before the infrastructure mini-feature is considered complete. Require a pinned MinIO image version for deterministic local development.

The existing config settings map directly:

| Setting | Local dev value |
|---|---|
| `S3_ENDPOINT_URL` | `http://localhost:9000` |
| `S3_ACCESS_KEY` | `minioadmin` |
| `S3_SECRET_KEY` | `minioadmin` |
| `S3_BUCKET_NAME` | `medical-documents` |

#### [MODIFY] [.env.example](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/.env.example)

Add the S3 local-dev values so new developers can copy them directly. The `.env.example` file is updated in the repository, and the local `.env` may be updated for development, but `.env` must never be committed.

> [!NOTE]
> The bucket `medical-documents` must be created on first use. The storage utility will auto-create it if it does not exist (see Storage Utility section below).

---

### Backend — Database

#### [MODIFY] [models.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/db/models.py)

Add a `MedicalDocument` model:

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `patient_id` | UUID FK → patients.id | indexed, ON DELETE CASCADE |
| `file_name` | String(255) | Original upload filename (metadata only) |
| `display_name` | String(255) | User-editable document name |
| `document_type` | String(50) | Constrained in API schema to specific allowed values. |
| `content_type` | String(100) | MIME type (`application/pdf`, etc.) |
| `file_size_bytes` | BigInteger | |
| `storage_key` | String(500) | S3 object key — format: `documents/{patient_id}/{uuid}` (internal only, **never exposed to client**) |
| `document_date` | Date (nullable) | Date on the document itself |
| `notes` | Text (nullable) | |
| `source_type` | String(50) | Default `PATIENT_REPORTED` |
| `uploaded_at` | DateTime(tz) | server_default now() |
| `created_at` | DateTime(tz) | |
| `updated_at` | DateTime(tz) | |

Add `documents` relationship on `Patient`.

#### [NEW] Alembic migration `0002_add_medical_documents.py`

Standard `op.create_table` + index on `patient_id`.

---

### Backend — Storage Utility

#### [NEW] [storage.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/core/storage.py)

Thin async wrapper around S3:

- `upload_file(key, data, content_type) → None`
- `download_file(key) → AsyncIterator[bytes]` — streams chunks for the download endpoint
- `delete_file(key) → None`
- `ensure_bucket() → None` — creates the bucket if it does not exist (must use lazy/first-use initialization rather than requiring MinIO to be available when unrelated backend endpoints start)

Uses `aiobotocore` with settings from `config.py`.

**Storage key format**: `documents/{patient_id}/{uuid}` — a bare UUID with no filename component. The original filename is stored only in the `file_name` column of the DB metadata row. No filename sanitization logic is needed.

---

### Backend — File Validation

#### [NEW] [file_validation.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/core/file_validation.py)

Validates uploads before they reach S3. Must operate within a **bounded read strategy**:
1. **Incremental Reading**: Read the file in chunks. Do not load arbitrarily large uploads completely into memory.
2. **Magic-byte signature**: Read the first chunk of the file content and verify the actual file signature matches the declared MIME type. Reject mismatches safely.
3. **File size**: Track cumulative size during the read process. Reject with `HTTPException(413)` as soon as the 20 MB limit is exceeded.
4. **Declared MIME type**: Reject if `content_type` is not in `{application/pdf, image/jpeg, image/png}`.

**Required flow:**
`bounded validation → rewind/reopen → stream upload to S3`

After bounded validation, the file must be rewound/reopened or otherwise streamed again for S3 upload. Do not load arbitrarily large files into memory.

| Format | Magic bytes |
|---|---|
| PDF | `%PDF` (hex `25 50 44 46`) |
| JPEG | `FF D8 FF` |
| PNG | `89 50 4E 47 0D 0A 1A 0A` |

Returns a validated `(content_type, file_size)` tuple on success, or raises an `HTTPException(413/422)` with a clear message on failure.

---

### Backend — Pydantic Schemas

#### [NEW] [document.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/schemas/document.py)

- `DocumentType` enum/literal: `lab_report`, `prescription`, `diagnostic_report`, `discharge_summary`, `medical_record`, `other`.
- `DocumentResponse` — all metadata fields returned after upload / list / get. **Must explicitly exclude `storage_key` and any other internal S3 identifiers.**
- `DocumentUpdate` — optional `display_name`, `document_type`, `document_date`, `notes`.

No `DocumentCreate` schema — metadata is derived from the multipart upload itself.

---

### Backend — Service Layer

#### [NEW] [documents.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/health/documents.py)

Functions following the existing pattern in [conditions.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/health/conditions.py):

| Function | Purpose |
|---|---|
| `create_document(db, patient_id, metadata, storage_key)` | Insert DB row after successful S3 upload |
| `get_documents(db, patient_id)` | List all documents for a patient (ordered by `uploaded_at desc`) |
| `get_document_by_id(db, document_id)` | Single lookup |
| `update_document(db, document, data)` | Patch mutable metadata |
| `delete_document(db, document)` | Delete DB row (caller handles S3 deletion) |

---

### Backend — API Route

#### [NEW] [documents.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/api/documents.py)

Router prefix: `/documents`, tag: `documents`.

| Endpoint | Method | Description |
|---|---|---|
| `POST /documents` | multipart/form-data | Upload file + optional metadata fields. Validates file (size, MIME, magic bytes via bounded reads). Uploads to S3, then creates DB record. Returns `DocumentResponse` (201). |
| `GET /documents` | JSON | List all documents for the authenticated patient. |
| `GET /documents/{id}` | JSON | Get single document metadata. |
| `GET /documents/{id}/download` | streaming | Authenticate user, enforce patient ownership, stream original file from S3 with correct `Content-Type` and safely constructed `Content-Disposition` headers. **Never interpolate the raw filename directly into an HTTP response header.** Prevent CR/LF/header-injection by using proper HTTP header encoding/sanitization. |
| `PATCH /documents/{id}` | JSON | Update mutable metadata (`display_name`, `document_type`, `document_date`, `notes`). |
| `DELETE /documents/{id}` | 204 | Delete S3 object + DB row (see consistency rules below). |

Every endpoint enforces `get_current_user` + patient isolation (same pattern as [conditions.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/api/conditions.py)).

**Storage / Database consistency rules:**

PostgreSQL + S3 cannot provide true distributed atomicity in this MVP without additional complex infrastructure (which is explicitly excluded). We will use a best-effort approach that avoids false success reporting:

Upload (`POST`):
1. Validate file incrementally.
2. Upload to S3.
3. Insert DB row.
4. **If DB insert fails** → attempt compensating S3 delete → return 500 failure to client.

Delete (`DELETE`):
1. Delete S3 object.
2. If S3 delete fails, abort and return 500 (DB row remains, file remains, system is consistent).
3. If S3 delete succeeds, delete DB row.
4. If DB delete fails, return 500. *(Note: This leaves a DB row pointing to a deleted S3 object, which we accept for this MVP over false success).*
5. **Do not return 204** unless both operations complete successfully. No silent successes.

#### [MODIFY] [main.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/app/main.py)

Register `documents_router`.

---

### Backend — Dependencies

#### [MODIFY] [requirements.txt](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/requirements.txt)

Add:
```
aiobotocore>=2.13.0
python-multipart>=0.0.9
```

`python-multipart` is required by FastAPI for `UploadFile` / form-data parsing.

---

### Frontend — API Client

#### [MODIFY] [api.ts](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/lib/api.ts)

Add types and `documentsApi` object:

- `DocumentType` type union matching the backend contract: `'lab_report' | 'prescription' | 'diagnostic_report' | 'discharge_summary' | 'medical_record' | 'other'`. The frontend must strictly use these values and not invent additional ones.
- `MedicalDocument` interface (mirrors `DocumentResponse`).
- `documentsApi.list(token)` — GET.
- `documentsApi.upload(token, file, metadata)` — POST multipart/form-data (uses `FormData`, **not** the existing JSON `request()` helper).
- `documentsApi.get(token, id)` — GET.
- `documentsApi.download(token, id)` — authenticated fetch to `GET /documents/{id}/download` with `Authorization: Bearer` header. Returns the response `Blob` for the frontend to trigger a save/display.
- `documentsApi.update(token, id, data)` — PATCH.
- `documentsApi.delete(token, id)` — DELETE.

---

### Frontend — UI Component

#### [NEW] [DocumentsList.tsx](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/DocumentsList.tsx)

Follows the same pattern as [ConditionsList.tsx](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/ConditionsList.tsx):

- List of uploaded documents (name, type derived from allowed `DocumentType` values, date, size).
- Upload button → file picker + optional metadata fields.
- Download / view button per document (uses `documentsApi.download()` to fetch blob, then triggers browser save/open).
- Edit metadata button (display name, type dropdown locked to allowed values, date, notes).
- Delete button with confirmation.
- Loading / error / empty states.

#### [MODIFY] [WorkspaceView.tsx](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/WorkspaceView.tsx)

Import and render `<DocumentsList />` in the workspace alongside the existing health entity lists.

---

### Tests

#### [NEW] [test_documents.py](file:///d:/Personal%20Projects/Personal%20HealthCare/backend/tests/test_documents.py)

Covering the acceptance criteria, validation matrix, security requirements, and failure-path consistency:

**Happy-path tests:**

| Test | Validates |
|---|---|
| Upload PDF → 201, metadata returned | Upload succeeds |
| GET /documents → includes uploaded doc | Stored document can be retrieved |
| GET /documents/{id} with owner token → 200 | Correct user ownership |
| GET /documents/{id}/download → streams correct bytes | Retrieval integrity |
| PATCH /documents/{id} → updated metadata | Metadata update works |
| DELETE /documents/{id} → 204, S3 object removed | Deletion works |

**Security & Isolation tests:**

| Test | Validates |
|---|---|
| API Responses do NOT contain `storage_key` or S3 info | Document response security |
| GET /documents/{id} with non-owner token → 403 | Unauthorized access fails |
| Upload file with MIME/magic-byte mismatch → 422 | Content validation catches spoofed type |
| Download document with unsafe filename containing CR/LF characters | Verifies `Content-Disposition` header injection prevention |

**Bounded Read & Limit tests:**

| Test | Validates |
|---|---|
| Upload oversized file → 413 | Incremental size validation |
| Upload disallowed MIME type → 422 | Format validation |

**Storage / DB consistency tests:**

| Test | Validates |
|---|---|
| Upload: S3 succeeds, DB insert fails → S3 object is cleaned up, client receives failure | Upload compensation |
| Delete: S3 delete fails → DB row is preserved, client receives failure | Delete consistency |
| Delete: DB delete fails after S3 delete → client receives failure, state is reported | Delete consistency without silent success |

S3 interactions will be mocked using a fake/mock S3 client in the test fixtures to keep tests fast and infrastructure-free. Failure-path tests inject deliberate errors into the mock.

#### [NEW] [DocumentsList.test.tsx](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/DocumentsList.test.tsx)

Component-level tests for upload, list, download, delete, and error states (same pattern as [ClinicalLists.test.tsx](file:///d:/Personal%20Projects/Personal%20HealthCare/frontend/src/components/ClinicalLists.test.tsx)).

---

## Execution Strategy (Mini-Features)

1. **M4-1 — Local MinIO + storage adapter**
   - **WHAT**: Add MinIO to Docker Compose, add S3 configs to `.env`, implement `aiobotocore` storage wrapper.
   - **WHY**: Establishes the foundational object storage layer without blocking on DB schema.
   - **Tests**: Unit tests must use a fake/mock S3 client and remain infrastructure-independent. Separately perform one real local MinIO connectivity/smoke check during M4-1 verification. Do not make the full automated suite depend on a running MinIO instance.
   - **Completion**: MinIO starts cleanly; storage utility passes unit tests.

2. **M4-2 — File validation**
   - **WHAT**: Implement `file_validation.py` for bounded size, MIME, and magic bytes.
   - **WHY**: Ensures security and constraints before files hit storage or DB.
   - **Tests**: Unit tests injecting valid/invalid MIME, oversized mock chunks, and invalid magic bytes.
   - **Completion**: Validation utility throws correct exceptions and passes valid files.

3. **M4-3 — MedicalDocument model + Alembic migration**
   - **WHAT**: Define `MedicalDocument` SQLAlchemy model and run migration.
   - **WHY**: Prepares metadata persistence layer.
   - **Tests**: Verify `alembic upgrade head` runs without errors; check schema.
   - **Completion**: Database schema includes the new table and relations.

4. **M4-4 — Document service + storage/DB consistency behavior**
   - **WHAT**: Implement `health/documents.py` service layer covering CRUD + storage/DB consistency.
   - **WHY**: Encapsulates business logic and orchestrates the S3 + PostgreSQL interactions safely.
   - **Tests**: Unit tests for S3 success/failure paths to verify consistency rules (e.g. compensating delete, 500 on S3 delete failure).
   - **Completion**: Service functions successfully coordinate with both DB and mock storage adapter.

5. **M4-5 — Document API**
   - **WHAT**: Implement `api/documents.py` (FastAPI routes) and Pydantic schemas.
   - **WHY**: Exposes the functionality to the frontend securely with user isolation.
   - **Tests**: API route tests for upload, list, download stream, update, and delete; test auth enforcement.
   - **Completion**: All endpoint tests pass, properly parsing multipart uploads and returning streams.

6. **M4-6 — Frontend document API + DocumentsList**
   - **WHAT**: Add API bindings to `api.ts` and create `DocumentsList.tsx` UI component.
   - **WHY**: Provides user interface to interact with documents.
   - **Tests**: UI component tests must cover the complete functional lifecycle: list/load, upload, download, edit metadata, delete, and loading/error states. Each action must verify the correct `documentsApi` method is called with the expected arguments.
   - **Completion**: Component renders correctly in isolated tests.

7. **M4-7 — Final M4 integration and verification**
   - **WHAT**: Mount the new UI component in `WorkspaceView` and perform manual end-to-end testing.
   - **WHY**: Confirms the full stack integration works in a real browser against a real local MinIO and DB.
   - **Tests**: Focused automated integration test verifying that `DocumentsList` is rendered in the authenticated workspace (in addition to manual verification).
   - **Completion**: All manual verification steps pass successfully.

---

## Verification Plan

### Automated Tests

```bash
# Backend
cd backend && python -m pytest tests/test_documents.py -v

# Full regression
cd backend && python -m pytest -v

# Frontend
cd frontend && npx vitest run
```

### Manual Verification

1. `docker compose up -d` — verify MinIO starts alongside Postgres.
2. Start backend + frontend locally.
3. Upload a PDF via the UI → verify it appears in the document list.
4. Click download → verify the original file saves/opens correctly.
5. Edit metadata → verify changes persist on refresh.
6. Delete → verify removal from list and MinIO.
7. Attempt to access another user's document ID → verify 403.
