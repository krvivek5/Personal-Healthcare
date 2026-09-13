import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuth } from '../context/AuthContext'
import { documentsApi, conditionsApi, symptomsApi, medicationsApi, allergiesApi, goalsApi, Condition } from '../lib/api'
import { WorkspaceView } from './WorkspaceView'

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  documentsApi: {
    list: vi.fn(),
    upload: vi.fn(),
    delete: vi.fn(),
  },
  conditionsApi: {
    list: vi.fn(),
    create: vi.fn(),
  },
  symptomsApi: { list: vi.fn() },
  medicationsApi: { list: vi.fn() },
  allergiesApi: { list: vi.fn() },
  goalsApi: { list: vi.fn(), create: vi.fn() },
}))

vi.mock('./HealthProfileView', () => ({
  HealthProfileView: () => <div data-testid="health-profile-view" />
}))

vi.mock('./TimelineView', () => ({
  TimelineView: () => <div data-testid="timeline-view" />
}))

const mockToken = 'mock-token'
const mockDoc = {
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

describe('Workspace Integration', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('shares document state between DocumentsList and ClinicalLists', async () => {
    // Start with 0 documents
    vi.mocked(documentsApi.list).mockResolvedValueOnce([])
    vi.mocked(conditionsApi.list).mockResolvedValueOnce([])
    vi.mocked(symptomsApi.list).mockResolvedValueOnce([])
    vi.mocked(medicationsApi.list).mockResolvedValueOnce([])
    vi.mocked(allergiesApi.list).mockResolvedValueOnce([])
    vi.mocked(goalsApi.list).mockResolvedValueOnce([])

    render(<WorkspaceView />)

    // The upload form should be on the page
    await waitFor(() => expect(screen.getByTestId('upload-form')).toBeInTheDocument())

    // Upload a new document
    const newDoc = { ...mockDoc, id: 'doc-2', display_name: 'My New Upload' }
    vi.mocked(documentsApi.upload).mockResolvedValueOnce(newDoc)

    // We expect list to be called again after upload
    vi.mocked(documentsApi.list).mockResolvedValueOnce([newDoc])

    const file = new File([new Uint8Array([0x25, 0x50])], 'test.pdf', { type: 'application/pdf' })
    const fileInput = screen.getByTestId('input-document-file') as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { value: [file] })
    fireEvent.change(fileInput)
    fireEvent.change(screen.getByTestId('input-document-type'), { target: { value: 'lab_report' } })
    fireEvent.change(screen.getByTestId('input-document-display-name'), { target: { value: 'My New Upload' } })

    fireEvent.submit(screen.getByTestId('upload-form'))

    // Wait for the new document to appear in the list
    await waitFor(() => expect(screen.getByText('My New Upload')).toBeInTheDocument())

    // Conditions form should be on the page
    await waitFor(() => expect(screen.getByTestId('input-condition-name')).toBeInTheDocument())

    // Change source type to SOURCE_DOCUMENT
    fireEvent.change(screen.getByTestId('input-condition-source-type'), { target: { value: 'SOURCE_DOCUMENT' } })

    // The newly uploaded document should be in the dropdown
    const sourceSelect = screen.getByTestId('input-condition-source-id') as HTMLSelectElement
    expect(sourceSelect).toBeInTheDocument()

    // Find the option
    const options = Array.from(sourceSelect.options)
    const newDocOption = options.find(opt => opt.text === 'My New Upload')
    expect(newDocOption).toBeDefined()
    expect(newDocOption?.value).toBe('doc-2')

    // Select it and submit
    fireEvent.change(screen.getByTestId('input-condition-name'), { target: { value: 'Diabetes' } })
    fireEvent.change(sourceSelect, { target: { value: 'doc-2' } })

    const newCond = { id: 'cond-1', name: 'Diabetes', status: 'active', is_chronic: true, source_type: 'SOURCE_DOCUMENT', source_id: 'doc-2' }
    vi.mocked(conditionsApi.create).mockResolvedValueOnce(newCond as Condition)

    fireEvent.click(screen.getByTestId('btn-add-condition'))

    await waitFor(() => {
      expect(conditionsApi.create).toHaveBeenCalledWith(mockToken, expect.objectContaining({
        name: 'Diabetes',
        source_type: 'SOURCE_DOCUMENT',
        source_id: 'doc-2'
      }))
    })

    // Now delete the document
    vi.mocked(documentsApi.delete).mockResolvedValueOnce(undefined)
    vi.mocked(documentsApi.list).mockResolvedValueOnce([])

    fireEvent.click(screen.getByTestId('btn-delete-document-doc-2'))
    fireEvent.click(screen.getByTestId('btn-confirm-delete'))

    // Wait for it to be removed
    await waitFor(() => expect(screen.queryByText('My New Upload')).not.toBeInTheDocument())

    // Check the selector again
    fireEvent.change(screen.getByTestId('input-condition-source-type'), { target: { value: 'SOURCE_DOCUMENT' } })
    const sourceSelect2 = screen.getByTestId('input-condition-source-id') as HTMLSelectElement
    const options2 = Array.from(sourceSelect2.options)
    const deletedOption = options2.find(opt => opt.text === 'My New Upload')
    expect(deletedOption).toBeUndefined()
  })
})
