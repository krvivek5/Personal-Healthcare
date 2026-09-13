import React, { useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import {
  documentsApi,
  MedicalDocument,
  DocumentType,
  DocumentUpdate,
} from '../lib/api'
import { ProvenanceBadge } from './ProvenanceBadge'

const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  lab_report: 'Lab Report',
  prescription: 'Prescription',
  diagnostic_report: 'Diagnostic Report',
  discharge_summary: 'Discharge Summary',
  medical_record: 'Medical Record',
  other: 'Other',
}

const DOCUMENT_TYPES: DocumentType[] = [
  'lab_report',
  'prescription',
  'diagnostic_report',
  'discharge_summary',
  'medical_record',
  'other',
]

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface DocumentsListProps {
  documents: MedicalDocument[]
  onDocumentsChange: () => void
}

export const DocumentsList: React.FC<DocumentsListProps> = ({ documents, onDocumentsChange }) => {
  const { session } = useAuth()
  const [error, setError] = useState<string | null>(null)

  // Upload form state
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [uploadDocType, setUploadDocType] = useState<DocumentType>('other')
  const [uploadDisplayName, setUploadDisplayName] = useState('')
  const [uploadDocDate, setUploadDocDate] = useState('')
  const [uploadNotes, setUploadNotes] = useState('')
  const [isUploading, setIsUploading] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDisplayName, setEditDisplayName] = useState('')
  const [editDocType, setEditDocType] = useState<DocumentType>('other')
  const [editDocDate, setEditDocDate] = useState('')
  const [editNotes, setEditNotes] = useState('')
  const [isSaving, setIsSaving] = useState(false)

  // Delete confirm state
  const [deletingId, setDeletingId] = useState<string | null>(null)

  // Download loading state
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault()
    const fileInput = fileInputRef.current
    if (!session?.access_token || !fileInput?.files?.[0]) return

    const file = fileInput.files[0]
    setIsUploading(true)
    setError(null)

    try {
      await documentsApi.upload(session.access_token, file, {
        document_type: uploadDocType,
        display_name: uploadDisplayName.trim() || undefined,
        document_date: uploadDocDate || null,
        notes: uploadNotes.trim() || null,
      })
      onDocumentsChange()
      // Reset form
      if (fileInput) fileInput.value = ''
      setUploadDisplayName('')
      setUploadDocDate('')
      setUploadNotes('')
      setUploadDocType('other')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload document')
    } finally {
      setIsUploading(false)
    }
  }

  const handleDownload = async (doc: MedicalDocument) => {
    if (!session?.access_token) return
    setDownloadingId(doc.id)
    setError(null)
    try {
      const blob = await documentsApi.download(session.access_token, doc.id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = doc.file_name
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to download document')
    } finally {
      setDownloadingId(null)
    }
  }

  const startEdit = (doc: MedicalDocument) => {
    setEditingId(doc.id)
    setEditDisplayName(doc.display_name)
    setEditDocType(doc.document_type)
    setEditDocDate(doc.document_date ?? '')
    setEditNotes(doc.notes ?? '')
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token) return
    setIsSaving(true)
    setError(null)
    try {
      const payload: DocumentUpdate = {
        display_name: editDisplayName.trim() || undefined,
        document_type: editDocType,
        document_date: editDocDate || null,
        notes: editNotes.trim() || null,
      }
      await documentsApi.update(session.access_token, id, payload)
      onDocumentsChange()
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update document')
    } finally {
      setIsSaving(false)
    }
  }

  const handleDeleteRequest = (id: string) => {
    setDeletingId(id)
  }

  const handleDeleteConfirm = async () => {
    if (!session?.access_token || !deletingId) return
    setError(null)
    try {
      await documentsApi.delete(session.access_token, deletingId)
      onDocumentsChange()
      setDeletingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete document')
      setDeletingId(null)
    }
  }



  return (
    <div data-testid="documents-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Medical Documents</h2>

      {error && <div data-testid="documents-error" className="text-red-500 mb-4">{error}</div>}

      {/* Upload form */}
      <form onSubmit={handleUpload} className="mb-6 border-b pb-4" data-testid="upload-form">
        <div className="flex flex-wrap gap-2 items-end">
          <div>
            <label className="block text-sm">File</label>
            <input
              ref={fileInputRef}
              type="file"
              data-testid="input-document-file"
              accept=".pdf,.jpg,.jpeg,.png"
              required
              className="border p-1 rounded text-sm"
            />
          </div>
          <div>
            <label className="block text-sm">Type</label>
            <select
              data-testid="input-document-type"
              value={uploadDocType}
              onChange={e => setUploadDocType(e.target.value as DocumentType)}
              className="border p-2 rounded"
            >
              {DOCUMENT_TYPES.map(t => (
                <option key={t} value={t}>{DOCUMENT_TYPE_LABELS[t]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm">Display Name</label>
            <input
              type="text"
              data-testid="input-document-display-name"
              value={uploadDisplayName}
              onChange={e => setUploadDisplayName(e.target.value)}
              className="border p-2 rounded"
              placeholder="Optional name"
            />
          </div>
          <div>
            <label className="block text-sm">Document Date</label>
            <input
              type="date"
              data-testid="input-document-date"
              value={uploadDocDate}
              onChange={e => setUploadDocDate(e.target.value)}
              className="border p-2 rounded"
            />
          </div>
          <div>
            <label className="block text-sm">Notes</label>
            <input
              type="text"
              data-testid="input-document-notes"
              value={uploadNotes}
              onChange={e => setUploadNotes(e.target.value)}
              className="border p-2 rounded"
              placeholder="Optional notes"
            />
          </div>
          <button
            type="submit"
            data-testid="btn-upload-document"
            disabled={isUploading}
            className="bg-blue-500 text-white px-4 py-2 rounded"
          >
            {isUploading ? 'Uploading...' : 'Upload'}
          </button>
        </div>
      </form>

      {/* Delete confirmation modal */}
      {deletingId && (
        <div data-testid="delete-confirm-modal" className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50">
          <div className="bg-white p-6 rounded shadow-lg max-w-sm w-full">
            <h3 className="text-lg font-semibold mb-2">Delete Document?</h3>
            <p className="text-sm text-gray-600 mb-4">This action cannot be undone.</p>
            <div className="flex justify-end gap-2">
              <button
                data-testid="btn-cancel-delete"
                onClick={() => setDeletingId(null)}
                className="px-4 py-2 border rounded"
              >
                Cancel
              </button>
              <button
                data-testid="btn-confirm-delete"
                onClick={handleDeleteConfirm}
                className="px-4 py-2 bg-red-500 text-white rounded"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Documents list */}
      {documents.length === 0 ? (
        <p data-testid="documents-empty">No documents uploaded yet.</p>
      ) : (
        <ul className="space-y-3">
          {documents.map(doc => (
            <li
              key={doc.id}
              data-testid={`document-item-${doc.id}`}
              className="border p-3 rounded"
            >
              {editingId === doc.id ? (
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap gap-2">
                    <div>
                      <label className="block text-xs">Display Name</label>
                      <input
                        type="text"
                        data-testid={`edit-display-name-${doc.id}`}
                        value={editDisplayName}
                        onChange={e => setEditDisplayName(e.target.value)}
                        className="border p-1 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs">Type</label>
                      <select
                        data-testid={`edit-doc-type-${doc.id}`}
                        value={editDocType}
                        onChange={e => setEditDocType(e.target.value as DocumentType)}
                        className="border p-1 rounded text-sm"
                      >
                        {DOCUMENT_TYPES.map(t => (
                          <option key={t} value={t}>{DOCUMENT_TYPE_LABELS[t]}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs">Document Date</label>
                      <input
                        type="date"
                        data-testid={`edit-doc-date-${doc.id}`}
                        value={editDocDate}
                        onChange={e => setEditDocDate(e.target.value)}
                        className="border p-1 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs">Notes</label>
                      <input
                        type="text"
                        data-testid={`edit-doc-notes-${doc.id}`}
                        value={editNotes}
                        onChange={e => setEditNotes(e.target.value)}
                        className="border p-1 rounded text-sm"
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      data-testid={`btn-save-document-${doc.id}`}
                      onClick={() => handleUpdate(doc.id)}
                      disabled={isSaving}
                      className="text-green-600 underline text-sm"
                    >
                      {isSaving ? 'Saving...' : 'Save'}
                    </button>
                    <button
                      data-testid={`btn-cancel-edit-${doc.id}`}
                      onClick={cancelEdit}
                      className="text-gray-500 underline text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{doc.display_name}</div>
                    <div className="text-sm text-gray-500 flex gap-2 mt-1">
                      <span className="bg-gray-100 px-2 py-0.5 rounded">
                        {DOCUMENT_TYPE_LABELS[doc.document_type] ?? doc.document_type}
                      </span>
                      <span>{formatBytes(doc.file_size_bytes)}</span>
                      {doc.document_date && <span>{doc.document_date}</span>}
                    </div>
                    {doc.notes && (
                      <div className="text-xs text-gray-400 mt-1">{doc.notes}</div>
                    )}
                    <div className="mt-1">
                      <ProvenanceBadge
                        sourceType={doc.source_type}
                        verificationState={doc.verification_state}
                      />
                    </div>
                  </div>
                  <div className="flex gap-2 ml-4 shrink-0">
                    <button
                      data-testid={`btn-download-document-${doc.id}`}
                      onClick={() => handleDownload(doc)}
                      disabled={downloadingId === doc.id}
                      className="text-blue-500 underline text-sm"
                    >
                      {downloadingId === doc.id ? 'Downloading...' : 'Download'}
                    </button>
                    <button
                      data-testid={`btn-edit-document-${doc.id}`}
                      onClick={() => startEdit(doc)}
                      className="text-blue-500 underline text-sm"
                    >
                      Edit
                    </button>
                    <button
                      data-testid={`btn-delete-document-${doc.id}`}
                      onClick={() => handleDeleteRequest(doc.id)}
                      className="text-red-500 underline text-sm"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
