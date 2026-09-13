import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuth } from '../context/AuthContext'
import { documentsApi, MedicalDocument } from '../lib/api'
import { DocumentsList } from './DocumentsList'

// Mock the AuthContext
vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

// Mock documentsApi
vi.mock('../lib/api', () => ({
  documentsApi: {
    list: vi.fn(),
    upload: vi.fn(),
    download: vi.fn(),
    get: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

const mockToken = 'mock-token'
const mockDoc: MedicalDocument = {
  id: 'doc-1',
  patient_id: 'p-1',
  file_name: 'blood_test.pdf',
  display_name: 'Blood Test Report',
  document_type: 'lab_report',
  content_type: 'application/pdf',
  file_size_bytes: 102400,
  document_date: '2026-01-15',
  notes: 'Fasting required',
  source_type: 'PATIENT_REPORTED',
  uploaded_at: '2026-01-15T10:00:00Z',
  created_at: '2026-01-15T10:00:00Z',
  updated_at: '2026-01-15T10:00:00Z',
}

describe('DocumentsList', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  // --- Render ---

  it('renders document list', async () => {
    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    expect(screen.getByTestId('documents-list')).toBeInTheDocument()
    expect(screen.getByTestId(`document-item-${mockDoc.id}`)).toBeInTheDocument()
    expect(screen.getByText('Blood Test Report')).toBeInTheDocument()
  })

  it('shows empty state when no documents', async () => {
    render(<DocumentsList documents={[]} onDocumentsChange={vi.fn()} />)

    expect(screen.getByTestId('documents-empty')).toBeInTheDocument()
  })

  // --- Upload ---

  it('calls documentsApi.upload with correct arguments on submit', async () => {
    const newDoc = { ...mockDoc, id: 'doc-2', display_name: 'My Upload' }
    vi.mocked(documentsApi.upload).mockResolvedValueOnce(newDoc)

    const mockOnChange = vi.fn()
    render(<DocumentsList documents={[]} onDocumentsChange={mockOnChange} />)

    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'test.pdf', {
      type: 'application/pdf',
    })

    const fileInput = screen.getByTestId('input-document-file') as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [file] })
    fireEvent.change(fileInput)

    const typeSelect = screen.getByTestId('input-document-type')
    fireEvent.change(typeSelect, { target: { value: 'lab_report' } })

    const nameInput = screen.getByTestId('input-document-display-name')
    fireEvent.change(nameInput, { target: { value: 'My Upload' } })

    const form = screen.getByTestId('upload-form')
    fireEvent.submit(form)

    await waitFor(() => expect(documentsApi.upload).toHaveBeenCalledOnce())

    expect(documentsApi.upload).toHaveBeenCalledWith(
      mockToken,
      file,
      expect.objectContaining({
        document_type: 'lab_report',
        display_name: 'My Upload',
      }),
    )

    expect(mockOnChange).toHaveBeenCalledOnce()
  })

  it('shows upload error when upload fails', async () => {
    vi.mocked(documentsApi.upload).mockRejectedValueOnce(new Error('Upload failed'))

    render(<DocumentsList documents={[]} onDocumentsChange={vi.fn()} />)

    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'test.pdf', {
      type: 'application/pdf',
    })
    const fileInput = screen.getByTestId('input-document-file') as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [file] })
    fireEvent.change(fileInput)

    fireEvent.submit(screen.getByTestId('upload-form'))

    await waitFor(() =>
      expect(screen.getByTestId('documents-error')).toHaveTextContent('Upload failed'),
    )
  })

  // --- Download ---

  it('calls documentsApi.download with correct id when download button clicked', async () => {
    vi.mocked(documentsApi.download).mockResolvedValueOnce(new Blob(['PDF content']))

    // Mock URL.createObjectURL
    const createObjectURL = vi.fn().mockReturnValue('blob:http://fake')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    // Prevent JSDOM navigation error by mocking anchor click
    const originalClick = HTMLAnchorElement.prototype.click
    const mockAnchorClick = vi.fn()
    HTMLAnchorElement.prototype.click = mockAnchorClick

    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    const downloadBtn = screen.getByTestId(`btn-download-document-${mockDoc.id}`)
    fireEvent.click(downloadBtn)

    await waitFor(() =>
      expect(documentsApi.download).toHaveBeenCalledWith(mockToken, mockDoc.id),
    )

    // Verify browser download behavior was triggered
    expect(mockAnchorClick).toHaveBeenCalled()

    // Restore original click
    HTMLAnchorElement.prototype.click = originalClick
  })

  it('shows error when download fails', async () => {
    vi.mocked(documentsApi.download).mockRejectedValueOnce(new Error('Download failed'))

    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-download-document-${mockDoc.id}`))

    await waitFor(() =>
      expect(screen.getByTestId('documents-error')).toHaveTextContent('Download failed'),
    )
  })

  // --- Edit metadata ---

  it('shows edit form when edit button clicked', async () => {
    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-edit-document-${mockDoc.id}`))
    expect(screen.getByTestId(`edit-display-name-${mockDoc.id}`)).toBeInTheDocument()
  })

  it('calls documentsApi.update with correct arguments on save', async () => {
    const updatedDoc = { ...mockDoc, display_name: 'Updated Name' }
    vi.mocked(documentsApi.update).mockResolvedValueOnce(updatedDoc)

    const mockOnChange = vi.fn()
    const { rerender } = render(<DocumentsList documents={[mockDoc]} onDocumentsChange={mockOnChange} />)

    fireEvent.click(screen.getByTestId(`btn-edit-document-${mockDoc.id}`))

    const nameInput = screen.getByTestId(`edit-display-name-${mockDoc.id}`)
    fireEvent.change(nameInput, { target: { value: 'Updated Name' } })

    fireEvent.click(screen.getByTestId(`btn-save-document-${mockDoc.id}`))

    await waitFor(() =>
      expect(documentsApi.update).toHaveBeenCalledWith(
        mockToken,
        mockDoc.id,
        expect.objectContaining({ display_name: 'Updated Name' }),
      ),
    )

    expect(mockOnChange).toHaveBeenCalledOnce()

    // Simulate parent re-rendering with updated documents
    rerender(<DocumentsList documents={[updatedDoc]} onDocumentsChange={mockOnChange} />)

    // Updated name should appear
    await waitFor(() => expect(screen.getByText('Updated Name')).toBeInTheDocument())
  })

  it('cancels edit without saving when cancel clicked', async () => {
    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-edit-document-${mockDoc.id}`))
    expect(screen.getByTestId(`edit-display-name-${mockDoc.id}`)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId(`btn-cancel-edit-${mockDoc.id}`))
    expect(screen.queryByTestId(`edit-display-name-${mockDoc.id}`)).not.toBeInTheDocument()
    expect(documentsApi.update).not.toHaveBeenCalled()
  })

  // --- Delete ---

  it('shows confirmation modal when delete button clicked', async () => {
    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-delete-document-${mockDoc.id}`))
    expect(screen.getByTestId('delete-confirm-modal')).toBeInTheDocument()
  })

  it('calls documentsApi.delete with correct id on confirm', async () => {
    vi.mocked(documentsApi.delete).mockResolvedValueOnce(undefined)

    const mockOnChange = vi.fn()
    const { rerender } = render(<DocumentsList documents={[mockDoc]} onDocumentsChange={mockOnChange} />)

    fireEvent.click(screen.getByTestId(`btn-delete-document-${mockDoc.id}`))
    fireEvent.click(screen.getByTestId('btn-confirm-delete'))

    await waitFor(() =>
      expect(documentsApi.delete).toHaveBeenCalledWith(mockToken, mockDoc.id),
    )

    expect(mockOnChange).toHaveBeenCalledOnce()

    // Simulate parent updating state
    rerender(<DocumentsList documents={[]} onDocumentsChange={mockOnChange} />)

    // Document removed from list
    await waitFor(() =>
      expect(screen.queryByTestId(`document-item-${mockDoc.id}`)).not.toBeInTheDocument(),
    )
  })

  it('cancels delete without calling api when cancel clicked', async () => {
    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-delete-document-${mockDoc.id}`))
    fireEvent.click(screen.getByTestId('btn-cancel-delete'))

    expect(documentsApi.delete).not.toHaveBeenCalled()
    expect(screen.queryByTestId('delete-confirm-modal')).not.toBeInTheDocument()
    // Document still visible
    expect(screen.getByTestId(`document-item-${mockDoc.id}`)).toBeInTheDocument()
  })

  it('shows error when delete fails', async () => {
    vi.mocked(documentsApi.delete).mockRejectedValueOnce(new Error('Delete failed'))

    render(<DocumentsList documents={[mockDoc]} onDocumentsChange={vi.fn()} />)

    fireEvent.click(screen.getByTestId(`btn-delete-document-${mockDoc.id}`))
    fireEvent.click(screen.getByTestId('btn-confirm-delete'))

    await waitFor(() =>
      expect(screen.getByTestId('documents-error')).toHaveTextContent('Delete failed'),
    )
  })
})
