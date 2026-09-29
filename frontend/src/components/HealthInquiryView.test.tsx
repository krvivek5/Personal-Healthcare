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

  // ─── Phase 2 Milestone 6 Slice 5: Timeline & Comparative Provenance UX ─────────

  it('renders TIMELINE citation card with dedicated badge, token, and verification state', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'When did my asthma start?',
      answer: 'According to your timeline records, asthma started in 2021 [1].',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'TIMELINE',
          record_id: '7b0d9124-b153-5249-b003-883c8466b0a2',
          label: 'Asthma (Condition Started) - 2021-03-15',
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'When did my asthma start?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('timeline-citation-card-1')).toBeInTheDocument()
    })

    expect(screen.getByTestId('citation-token-1')).toHaveTextContent('[1]')
    expect(screen.getByTestId('citation-type-1')).toHaveTextContent('TIMELINE')
    expect(screen.getByTestId('citation-state-1')).toHaveTextContent('SOURCE RECORDED')
    expect(screen.getByTestId('timeline-citation-label-1')).toHaveTextContent('Asthma (Condition Started) - 2021-03-15')
    expect(screen.getByTestId('inspect-details-btn-1')).toHaveTextContent('Inspect Details')

    // Document-specific elements must NOT be present
    expect(screen.queryByTestId('document-citation-card-1')).not.toBeInTheDocument()
    expect(screen.queryByTestId('download-doc-btn-1')).not.toBeInTheDocument()
    expect(screen.queryByTestId('inspect-excerpt-btn-1')).not.toBeInTheDocument()
  })

  it('toggles inline details panel on TIMELINE citation card', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'When did my asthma start?',
      answer: 'Your asthma started in 2021 [1].',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'TIMELINE',
          record_id: '7b0d9124-b153-5249-b003-883c8466b0a2',
          label: 'Asthma (Condition Started) - 2021-03-15',
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'When did my asthma start?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inspect-details-btn-1')).toBeInTheDocument()
    })

    const inspectBtn = screen.getByTestId('inspect-details-btn-1')
    expect(screen.queryByTestId('citation-details-1')).not.toBeInTheDocument()

    // Expand details
    fireEvent.click(inspectBtn)
    expect(screen.getByTestId('citation-details-1')).toBeInTheDocument()
    expect(screen.getByText('7b0d9124-b153-5249-b003-883c8466b0a2')).toBeInTheDocument()
    expect(screen.getByText('TIMELINE', { selector: 'div' })).toBeInTheDocument()
    expect(screen.getByText('SOURCE_RECORDED', { selector: 'div' })).toBeInTheDocument()
    expect(inspectBtn).toHaveTextContent('Hide Details')

    // Collapse details
    fireEvent.click(inspectBtn)
    expect(screen.queryByTestId('citation-details-1')).not.toBeInTheDocument()
    expect(inspectBtn).toHaveTextContent('Inspect Details')
  })

  it('renders mixed provenance citations (DOCUMENT, STRUCTURED, TIMELINE) in exact server order and enforces mutual exclusion on details expansion', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'What is my comprehensive asthma history?',
      answer: 'Asthma history documented across records [1], conditions [2], and timeline events [3].',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'DOCUMENT',
          record_id: 'doc-uuid-1',
          label: 'Pulmonary Function Test (2026-01-15)',
          verification_state: 'SOURCE_RECORDED',
        },
        {
          citation_id: 2,
          entity_type: 'CONDITION',
          record_id: 'cond-uuid-2',
          label: 'Asthma',
          verification_state: 'VERIFIED',
        },
        {
          citation_id: 3,
          entity_type: 'TIMELINE',
          record_id: 'tl-uuid-3',
          label: 'Asthma Onset (Condition Started) - 2021-03-15',
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'What is my comprehensive asthma history?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('document-citation-card-1')).toBeInTheDocument()
    })

    // Citations appear in exact order without re-ranking
    expect(screen.getByTestId('citation-1')).toBeInTheDocument()
    expect(screen.getByTestId('document-citation-card-1')).toBeInTheDocument()

    expect(screen.getByTestId('citation-2')).toBeInTheDocument()
    expect(screen.getByText('CONDITION:')).toBeInTheDocument()

    expect(screen.getByTestId('citation-3')).toBeInTheDocument()
    expect(screen.getByTestId('timeline-citation-card-3')).toBeInTheDocument()

    // Test shared details state mutual exclusion across DOCUMENT and TIMELINE
    const docInspectBtn = screen.getByTestId('inspect-details-btn-1')
    const tlInspectBtn = screen.getByTestId('inspect-details-btn-3')

    // Open citation 1 details
    fireEvent.click(docInspectBtn)
    expect(screen.getByTestId('citation-details-1')).toBeInTheDocument()
    expect(screen.queryByTestId('citation-details-3')).not.toBeInTheDocument()

    // Open citation 3 details -> closes citation 1 details
    fireEvent.click(tlInspectBtn)
    expect(screen.getByTestId('citation-details-3')).toBeInTheDocument()
    expect(screen.queryByTestId('citation-details-1')).not.toBeInTheDocument()

    // Toggle citation 3 details -> closes citation 3 details
    fireEvent.click(tlInspectBtn)
    expect(screen.queryByTestId('citation-details-3')).not.toBeInTheDocument()
  })

  it('renders comparative trajectory answer with preserved whitespace and authoritative locked bounded qualifier', async () => {
    const lockedQualifier = 'Note: This summary highlights key milestone dates (Baseline, Intermediate, and Latest). Additional qualified dated candidates were identified in the evaluated evidence set and are not shown in this summary.'
    const comparativeAnswer = `In 2021, you were diagnosed with Mild Intermittent Asthma [1].

By 2024, your symptoms escalated to Moderate Persistent Asthma [2].

Your latest 2026 pulmonary function test confirms well-controlled status on inhaled corticosteroids [3].

${lockedQualifier}`

    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'How has my asthma progressed between 2021 and 2026?',
      answer: comparativeAnswer,
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'TIMELINE',
          record_id: 'tl-1',
          label: 'Asthma (Condition Started) - 2021-03-15',
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'How has my asthma progressed between 2021 and 2026?' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('inquiry-answer')).toBeInTheDocument()
    })

    const answerElement = screen.getByTestId('inquiry-answer')
    expect(answerElement).toHaveTextContent(lockedQualifier)
    expect(answerElement).toHaveStyle({ whiteSpace: 'pre-wrap' })
    expect(answerElement).toHaveStyle({ wordBreak: 'break-word' })
  })

  it('handles missing optional fields and applies deterministic fallbacks on TIMELINE citations', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Test fallbacks',
      answer: 'Testing fallbacks.',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'TIMELINE',
          record_id: '', // Case A: missing record_id
          label: 'Event 1 - 2021-01-01',
          verification_state: 'SOURCE_RECORDED',
        },
        {
          citation_id: 2,
          entity_type: 'TIMELINE',
          record_id: 'tl-uuid-2',
          label: 'Event 2 - 2022-02-02',
          verification_state: undefined as unknown as string, // Case B: missing verification_state
        },
        {
          citation_id: 3,
          entity_type: 'TIMELINE',
          record_id: 'tl-uuid-3',
          label: 'Event 3 - 2023-03-03',
          verification_state: 'UNKNOWN_TEST_STATE', // Case C: unrecognized verification_state
        },
        {
          citation_id: 4,
          entity_type: 'TIMELINE',
          record_id: 'tl-uuid-4',
          label: '   ', // Case D: empty/whitespace label
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Test fallbacks' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('timeline-citation-card-1')).toBeInTheDocument()
    })

    // Case A: missing record_id -> details displays 'not recorded'
    fireEvent.click(screen.getByTestId('inspect-details-btn-1'))
    expect(screen.getByTestId('citation-details-1')).toBeInTheDocument()
    expect(screen.getByText('not recorded')).toBeInTheDocument()

    // Case B: missing verification_state -> badge and details display 'UNCERTAIN' without crash
    expect(screen.getByTestId('citation-state-2')).toHaveTextContent('UNCERTAIN')
    fireEvent.click(screen.getByTestId('inspect-details-btn-2'))
    expect(screen.getByTestId('citation-details-2')).toBeInTheDocument()
    expect(screen.getByText('UNCERTAIN', { selector: 'div' })).toBeInTheDocument()

    // Case C: unrecognized verification_state -> normalizes to 'UNCERTAIN'
    expect(screen.getByTestId('citation-state-3')).toHaveTextContent('UNCERTAIN')
    fireEvent.click(screen.getByTestId('inspect-details-btn-3'))
    expect(screen.getByTestId('citation-details-3')).toBeInTheDocument()
    expect(screen.getByText('UNCERTAIN', { selector: 'div' })).toBeInTheDocument()

    // Case D: empty label -> primary label and details panel both display 'Timeline Event'
    expect(screen.getByTestId('timeline-citation-label-4')).toHaveTextContent('Timeline Event')
    fireEvent.click(screen.getByTestId('inspect-details-btn-4'))
    expect(screen.getByTestId('citation-details-4')).toBeInTheDocument()
    expect(screen.getByTestId('citation-details-4')).toHaveTextContent('Timeline Event: Timeline Event')
  })

  it('applies subtle distinct color styling for PARTIALLY_SUFFICIENT and INSUFFICIENT evidence states', async () => {
    // PARTIALLY_SUFFICIENT
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Query 1',
      answer: 'Partial evidence.',
      evidence_status: 'PARTIALLY_SUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    const { unmount } = render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Query 1' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-status-PARTIALLY_SUFFICIENT')).toBeInTheDocument()
    })
    expect(screen.getByTestId('evidence-status-PARTIALLY_SUFFICIENT')).toHaveTextContent('PARTIALLY SUFFICIENT')

    unmount()

    // INSUFFICIENT
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Query 2',
      answer: 'No evidence found.',
      evidence_status: 'INSUFFICIENT',
      citations: [],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Query 2' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('evidence-status-INSUFFICIENT')).toBeInTheDocument()
    })
    expect(screen.getByTestId('evidence-status-INSUFFICIENT')).toHaveTextContent('INSUFFICIENT')
  })

  it('supports multiple TIMELINE citations across distinct longitudinal milestone dates', async () => {
    vi.mocked(healthInquiryApi.submit).mockResolvedValueOnce({
      query: 'Track my asthma over time',
      answer: 'Diagnosed in 2021 [1] with flare in 2024 [2].',
      evidence_status: 'SUFFICIENT',
      citations: [
        {
          citation_id: 1,
          entity_type: 'TIMELINE',
          record_id: 'tl-1',
          label: 'Asthma (Condition Started) - 2021-03-15',
          verification_state: 'SOURCE_RECORDED',
        },
        {
          citation_id: 2,
          entity_type: 'TIMELINE',
          record_id: 'tl-2',
          label: 'Asthma Flare (Symptom Reported) - 2024-06-10',
          verification_state: 'SOURCE_RECORDED',
        },
      ],
      safety: { triggered: false, advisory_message: null },
      generated_at: '2026-09-29T18:00:00Z',
    })

    render(<HealthInquiryView />)
    fireEvent.change(screen.getByTestId('inquiry-query-input'), { target: { value: 'Track my asthma over time' } })
    fireEvent.click(screen.getByTestId('inquiry-submit-btn'))

    await waitFor(() => {
      expect(screen.getByTestId('timeline-citation-card-1')).toBeInTheDocument()
    })

    expect(screen.getByTestId('timeline-citation-card-2')).toBeInTheDocument()
    expect(screen.getByTestId('citation-token-1')).toHaveTextContent('[1]')
    expect(screen.getByTestId('citation-token-2')).toHaveTextContent('[2]')
    expect(screen.getByTestId('timeline-citation-label-1')).toHaveTextContent('Asthma (Condition Started) - 2021-03-15')
    expect(screen.getByTestId('timeline-citation-label-2')).toHaveTextContent('Asthma Flare (Symptom Reported) - 2024-06-10')
  })
})
