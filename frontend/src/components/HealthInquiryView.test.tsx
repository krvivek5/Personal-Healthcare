import React from 'react'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuth } from '../context/AuthContext'
import { healthInquiryApi, documentsApi, ApiError, HealthInquiryResponse } from '../lib/api'
import { HealthInquiryView } from './HealthInquiryView'

// Mock AuthContext
vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

// Mock API
vi.mock('../lib/api', () => ({
  healthInquiryApi: {
    submit: vi.fn(),
  },
  documentsApi: {
    download: vi.fn(),
  },
  ApiError: class extends Error {
    constructor(public status: number, message: string) {
      super(message)
      this.name = 'ApiError'
    }
  }
}))

describe('HealthInquiryView', () => {
  const mockToken = 'mock-token'

  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('renders initially', () => {
    render(<HealthInquiryView />)
    expect(screen.getByText('Ask a Health Question')).toBeInTheDocument()
    expect(screen.getByTestId('inquiry-query-input')).toBeInTheDocument()
    expect(screen.getByTestId('inquiry-submit-btn')).toBeDisabled()
    expect(screen.queryByTestId('inquiry-response-container')).not.toBeInTheDocument()
  })

  it('disables submit on empty or whitespace queries', () => {
    render(<HealthInquiryView />)
    const input = screen.getByTestId('inquiry-query-input')
    const btn = screen.getByTestId('inquiry-submit-btn')
    
    expect(btn).toBeDisabled()

    fireEvent.change(input, { target: { value: '   ' } })
    expect(btn).toBeDisabled()

    fireEvent.change(input, { target: { value: 'What is my blood type?' } })
    expect(btn).not.toBeDisabled()
  })

  it('handles successful submission and loading state', async () => {
    let resolveSubmit: (value: unknown) => void
    const submitPromise = new Promise((resolve) => {
      resolveSubmit = resolve
    })
    
    vi.mocked(healthInquiryApi.submit).mockReturnValue(submitPromise as unknown as Promise<HealthInquiryResponse>)

    render(<HealthInquiryView />)
    const input = screen.getByTestId('inquiry-query-input')
    const btn = screen.getByTestId('inquiry-submit-btn')

    fireEvent.change(input, { target: { value: 'Test query' } })
    fireEvent.click(btn)

    // Check loading state
    expect(btn).toBeDisabled()
    expect(btn).toHaveTextContent('Searching...')
    expect(input).toBeDisabled()
    
    expect(healthInquiryApi.submit).toHaveBeenCalledWith(mockToken, { query: 'Test query' })

    // Resolve promise
    resolveSubmit!({
      query: 'Test query',
      answer: 'This is the answer',
      evidence_status: 'SUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-14T10:00:00Z'
    })

    await waitFor(() => {
      expect(screen.getByTestId('inquiry-response-container')).toBeInTheDocument()
    })

    expect(btn).not.toBeDisabled()
    expect(btn).toHaveTextContent('Ask')
    expect(input).not.toBeDisabled()
  })

  it('displays a SUFFICIENT response correctly', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test',
      answer: 'All good.',
      evidence_status: 'SUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-14T10:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-status-SUFFICIENT')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inquiry-answer')).toHaveTextContent('All good.')
    expect(screen.queryByTestId('inquiry-safety-advisory')).not.toBeInTheDocument()
  })

  it('displays a PARTIALLY_SUFFICIENT response correctly', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test',
      answer: 'Partial info.',
      evidence_status: 'PARTIALLY_SUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-14T10:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-status-PARTIALLY_SUFFICIENT')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inquiry-answer')).toHaveTextContent('Partial info.')
  })

  it('displays an INSUFFICIENT response correctly without assuming safety risk', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test',
      answer: 'No info.',
      evidence_status: 'INSUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-14T10:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-status-INSUFFICIENT')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('inquiry-safety-advisory')).not.toBeInTheDocument()
  })

  it('renders citation/provenance using the backend fields', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test',
      answer: 'Info.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'CONDITION',
          record_id: 'uuid-1',
          label: 'Asthma',
          verification_state: 'VERIFIED'
        },
        {
          citation_id: 2,
          entity_type: 'DOCUMENT',
          record_id: 'uuid-2',
          label: 'Lab Report',
          verification_state: 'SOURCE_RECORDED',
          chunk_id: 'chunk-123',
          page_number: 4,
          passage_text: 'This is the passage.'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-14T10:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('citation-1')).toBeInTheDocument()
    })
    
    expect(screen.getByText('[1]')).toBeInTheDocument()
    expect(screen.getByText(/Asthma/)).toBeInTheDocument()
    expect(screen.getByText(/CONDITION:/)).toBeInTheDocument()
    expect(screen.getByText(/VERIFIED/)).toBeInTheDocument()

    expect(screen.getByTestId('citation-2')).toBeInTheDocument()
    expect(screen.getByText('[2]')).toBeInTheDocument()
    expect(screen.getByText(/Lab Report/)).toBeInTheDocument()
    expect(screen.getByTestId('citation-page-2')).toHaveTextContent('PAGE 4')
  })

  it('renders safety advisory independently of evidence status', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test',
      answer: 'Answer.',
      evidence_status: 'SUFFICIENT', // Status is fine, but safety triggered
      citations: [],
      safety: { triggered: true, advisory_message: 'Please call 911 if experiencing chest pain.' },
      generated_at: '2026-09-14T10:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inquiry-safety-advisory')).toBeInTheDocument()
    })
    
    expect(screen.getByText('Safety Advisory')).toBeInTheDocument()
    expect(screen.getByText('Please call 911 if experiencing chest pain.')).toBeInTheDocument()
    // Verify evidence status is still what it returned
    expect(screen.getByTestId('evidence-status-SUFFICIENT')).toBeInTheDocument()
  })

  it('handles ApiError correctly', async () => {
    vi.mocked(healthInquiryApi.submit).mockRejectedValueOnce(new ApiError(400, 'Invalid query format'))

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inquiry-error')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inquiry-error')).toHaveTextContent('Error: Invalid query format')
    expect(screen.queryByTestId('inquiry-response-container')).not.toBeInTheDocument()
  })

  it('handles general API errors correctly', async () => {
    vi.mocked(healthInquiryApi.submit).mockRejectedValueOnce(new TypeError('Network Error'))

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inquiry-error')).toBeInTheDocument()
    })
    expect(screen.getByTestId('inquiry-error')).toHaveTextContent('An unexpected error occurred while processing your inquiry.')
  })

  it('renders document citation cards with badges, metadata, and actions', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your uploaded Comprehensive Metabolic Panel, records confirm creatinine.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Comprehensive Metabolic Panel (2026-08-12)',
          verification_state: 'SOURCE_RECORDED'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('document-citation-card-1')).toBeInTheDocument()
    })

    expect(screen.getByTestId('citation-token-1')).toHaveTextContent('[1]')
    expect(screen.getByTestId('citation-type-1')).toHaveTextContent('DOCUMENT')
    expect(screen.getByTestId('citation-state-1')).toHaveTextContent('SOURCE RECORDED')
    expect(screen.getByText('Comprehensive Metabolic Panel (2026-08-12)')).toBeInTheDocument()
    expect(screen.getByTestId('inspect-details-btn-1')).toHaveTextContent('Inspect Details')
    expect(screen.getByTestId('download-doc-btn-1')).toHaveTextContent('Download Document')
    expect(screen.queryByTestId('citation-details-1')).not.toBeInTheDocument()
  })

  it('toggles inline details panel when inspect details button is clicked', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your records, creatinine was normal.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Lab Report (2026-08-12)',
          verification_state: 'SOURCE_RECORDED'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inspect-details-btn-1')).toBeInTheDocument()
    })

    const inspectBtn = screen.getByTestId('inspect-details-btn-1')
    fireEvent.click(inspectBtn)

    expect(screen.getByTestId('citation-details-1')).toBeInTheDocument()
    expect(screen.getByText('doc-uuid-1')).toBeInTheDocument()
    expect(inspectBtn).toHaveTextContent('Hide Details')

    fireEvent.click(inspectBtn)
    expect(screen.queryByTestId('citation-details-1')).not.toBeInTheDocument()
    expect(inspectBtn).toHaveTextContent('Inspect Details')
  })

  it('triggers document download when download button is clicked', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your records, creatinine was normal.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Lab Report (2026-08-12)',
          verification_state: 'SOURCE_RECORDED'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    vi.mocked(documentsApi.download).mockResolvedValueOnce(new Blob(['PDF content']))

    const createObjectURL = vi.fn().mockReturnValue('blob:http://fake')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    const originalClick = HTMLAnchorElement.prototype.click
    const mockAnchorClick = vi.fn()
    HTMLAnchorElement.prototype.click = mockAnchorClick

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('download-doc-btn-1')).toBeInTheDocument()
    })

    const downloadBtn = screen.getByTestId('download-doc-btn-1')
    fireEvent.click(downloadBtn)

    await waitFor(() => {
      expect(documentsApi.download).toHaveBeenCalledWith(mockToken, 'doc-uuid-1')
    })
    expect(mockAnchorClick).toHaveBeenCalled()

    HTMLAnchorElement.prototype.click = originalClick
  })

  it('displays download error when document download fails', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your records, creatinine was normal.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Lab Report (2026-08-12)',
          verification_state: 'SOURCE_RECORDED'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    vi.mocked(documentsApi.download).mockRejectedValueOnce(new Error('Network error downloading file'))

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('download-doc-btn-1')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('download-doc-btn-1'))

    await waitFor(() => {
      expect(screen.getByTestId('download-error-1')).toBeInTheDocument()
    })
    expect(screen.getByTestId('download-error-1')).toHaveTextContent('Network error downloading file')
  })

  it('displays downloading state and disables download button while download is pending', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your records, creatinine was normal.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Lab Report (2026-08-12)',
          verification_state: 'SOURCE_RECORDED'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    let resolveDownload!: (value: Blob) => void
    const pendingPromise = new Promise<Blob>((resolve) => {
      resolveDownload = resolve
    })
    vi.mocked(documentsApi.download).mockReturnValueOnce(pendingPromise)

    const createObjectURL = vi.fn().mockReturnValue('blob:http://fake')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })

    const originalClick = HTMLAnchorElement.prototype.click
    const mockAnchorClick = vi.fn()
    HTMLAnchorElement.prototype.click = mockAnchorClick

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('download-doc-btn-1')).toBeInTheDocument()
    })

    const downloadBtn = screen.getByTestId('download-doc-btn-1')
    expect(downloadBtn).toHaveTextContent('Download Document')
    expect(downloadBtn).not.toBeDisabled()

    fireEvent.click(downloadBtn)

    await waitFor(() => {
      expect(downloadBtn).toHaveTextContent('Downloading...')
    })
    expect(downloadBtn).toBeDisabled()

    await act(async () => {
      resolveDownload(new Blob(['PDF content']))
    })

    await waitFor(() => {
      expect(downloadBtn).toHaveTextContent('Download Document')
    })
    expect(downloadBtn).not.toBeDisabled()
    expect(mockAnchorClick).toHaveBeenCalled()

    HTMLAnchorElement.prototype.click = originalClick
  })

  it('renders explicit missing-page behavior and excerpt toggle when page is null', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What was my creatinine?',
      answer: 'According to your records, creatinine was normal.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Lab Report',
          verification_state: 'SOURCE_RECORDED',
          page_number: null,
          chunk_id: 'chunk-999',
          passage_text: 'Creatinine was normal.'
        }
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-16T12:00:00Z'
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What was my creatinine?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('citation-1')).toBeInTheDocument()
    })

    // No PAGE badge should be rendered
    expect(screen.queryByTestId('citation-page-1')).not.toBeInTheDocument()
    expect(screen.queryByText(/PAGE null/i)).not.toBeInTheDocument()

    const excerptBtn = screen.getByTestId('inspect-excerpt-btn-1')
    fireEvent.click(excerptBtn)

    expect(screen.getByTestId('passage-excerpt-1')).toBeInTheDocument()
    expect(screen.getByText('Retrieved Passage Excerpt (Page not recorded):')).toBeInTheDocument()
    expect(screen.getByText('Creatinine was normal.')).toBeInTheDocument()
    expect(excerptBtn).toHaveTextContent('Hide Excerpt')

    const detailsBtn = screen.getByTestId('inspect-details-btn-1')
    fireEvent.click(detailsBtn)

    expect(screen.getByTestId('citation-details-1')).toBeInTheDocument()
    expect(screen.getByText('not recorded', { selector: 'div:nth-child(4)' })).toBeInTheDocument()
    expect(screen.getByText('chunk-999')).toBeInTheDocument()
  })
})
