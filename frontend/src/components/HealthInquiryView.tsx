import React, { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { healthInquiryApi, documentsApi, HealthInquiryResponse, ApiError } from '../lib/api'

export const HealthInquiryView: React.FC = () => {
  const { session } = useAuth()
  const [query, setQuery] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [response, setResponse] = useState<HealthInquiryResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [downloadError, setDownloadError] = useState<{ citationId: number; message: string } | null>(null)
  const [expandedCitationId, setExpandedCitationId] = useState<number | null>(null)

  const handleDownloadDocument = async (recordId: string, citationId: number, fileName?: string) => {
    if (!session?.access_token) return
    setDownloadingId(recordId)
    setDownloadError(null)

    try {
      const blob = await documentsApi.download(session.access_token, recordId)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName || `document-${recordId}`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      setDownloadError({
        citationId,
        message: err instanceof Error ? err.message : 'Failed to download document',
      })
    } finally {
      setDownloadingId(null)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim() || !session?.access_token) return

    setIsLoading(true)
    setError(null)
    setResponse(null)
    setDownloadError(null)
    setExpandedCitationId(null)

    try {
      const result = await healthInquiryApi.submit(session.access_token, { query: query.trim() })
      setResponse(result)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`Error: ${err.message}`)
      } else {
        setError('An unexpected error occurred while processing your inquiry.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="health-inquiry-view" data-testid="health-inquiry-view" style={{ marginBottom: '2rem' }}>
      <h3 style={{ marginBottom: '1rem', color: '#334155' }}>Ask a Health Question</h3>
      
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
        <input
          type="text"
          data-testid="inquiry-query-input"
          placeholder="e.g., When was my last tetanus shot?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={isLoading}
          style={{
            flex: 1,
            padding: '0.75rem',
            border: '1px solid #cbd5e1',
            borderRadius: '6px',
            fontSize: '1rem'
          }}
        />
        <button
          type="submit"
          data-testid="inquiry-submit-btn"
          disabled={isLoading || !query.trim()}
          style={{
            background: '#0284c7',
            color: 'white',
            border: 'none',
            padding: '0.75rem 1.5rem',
            borderRadius: '6px',
            cursor: isLoading || !query.trim() ? 'not-allowed' : 'pointer',
            opacity: isLoading || !query.trim() ? 0.7 : 1,
            fontSize: '1rem',
            fontWeight: 500
          }}
        >
          {isLoading ? 'Searching...' : 'Ask'}
        </button>
      </form>

      {error && (
        <div data-testid="inquiry-error" style={{ color: '#b91c1c', padding: '0.75rem', background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '6px', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {response && (
        <div data-testid="inquiry-response-container" style={{ border: '1px solid #e2e8f0', borderRadius: '8px', overflow: 'hidden' }}>
          
          {/* Safety Advisory - Visually Prominent Warning */}
          {response.safety.triggered && response.safety.advisory_message && (
            <div data-testid="inquiry-safety-advisory" style={{ background: '#fee2e2', color: '#991b1b', padding: '1rem', borderBottom: '1px solid #fca5a5', fontWeight: 500 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                <span style={{ fontSize: '1.25rem' }}>⚠️</span>
                <strong>Safety Advisory</strong>
              </div>
              <p style={{ margin: 0 }}>{response.safety.advisory_message}</p>
            </div>
          )}

          <div style={{ padding: '1.5rem', background: '#f8fafc' }}>
            {/* Evidence Status - Neutral Presentation */}
            <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span style={{ fontSize: '0.85rem', color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Evidence Status:</span>
              <span
                data-testid={`evidence-status-${response.evidence_status}`}
                style={{
                  display: 'inline-block',
                  padding: '0.25rem 0.5rem',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  borderRadius: '4px',
                  background: '#f1f5f9',
                  color: '#475569',
                  border: '1px solid #cbd5e1'
                }}
              >
                {response.evidence_status.replace('_', ' ')}
              </span>
            </div>

            {/* Answer */}
            <div data-testid="inquiry-answer" style={{ fontSize: '1.1rem', color: '#1e293b', lineHeight: '1.6', marginBottom: '1.5rem', whiteSpace: 'pre-wrap' }}>
              {response.answer}
            </div>

            {/* Citations */}
            {response.citations.length > 0 && (
              <div data-testid="inquiry-citations">
                <h4 style={{ fontSize: '0.9rem', color: '#64748b', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sources</h4>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                  {response.citations.map((citation) => {
                    const isDocument = citation.entity_type === 'DOCUMENT'
                    if (!isDocument) {
                      return (
                        <li key={`${citation.entity_type}-${citation.record_id}`} data-testid={`citation-${citation.citation_id}`} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.9rem' }}>
                          <span style={{ color: '#0284c7', fontWeight: 600 }}>[{citation.citation_id}]</span>
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <span style={{ color: '#334155' }}>
                              <strong>{citation.entity_type}:</strong> {citation.label}
                            </span>
                            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
                              State: {citation.verification_state}
                            </span>
                          </div>
                        </li>
                      )
                    }

                    const isExpanded = expandedCitationId === citation.citation_id
                    const isDownloading = downloadingId === citation.record_id
                    const hasError = downloadError?.citationId === citation.citation_id

                    return (
                      <li
                        key={`${citation.entity_type}-${citation.record_id}`}
                        data-testid={`citation-${citation.citation_id}`}
                        style={{ listStyle: 'none' }}
                      >
                        <div
                          data-testid={`document-citation-card-${citation.citation_id}`}
                          style={{
                            border: '1px solid #cbd5e1',
                            borderRadius: '8px',
                            padding: '1rem',
                            background: '#ffffff',
                            boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.05)',
                          }}
                        >
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                              <span
                                data-testid={`citation-token-${citation.citation_id}`}
                                style={{
                                  color: '#0284c7',
                                  fontWeight: 700,
                                  fontSize: '0.95rem',
                                  background: '#e0f2fe',
                                  padding: '0.2rem 0.5rem',
                                  borderRadius: '4px',
                                }}
                              >
                                [{citation.citation_id}]
                              </span>
                              <span
                                data-testid={`citation-type-${citation.citation_id}`}
                                style={{
                                  background: '#f1f5f9',
                                  color: '#475569',
                                  fontSize: '0.75rem',
                                  fontWeight: 600,
                                  padding: '0.2rem 0.4rem',
                                  borderRadius: '4px',
                                  border: '1px solid #e2e8f0',
                                  textTransform: 'uppercase',
                                }}
                              >
                                {citation.entity_type}
                              </span>
                              <span
                                data-testid={`citation-state-${citation.citation_id}`}
                                style={{
                                  background: '#ecfdf5',
                                  color: '#047857',
                                  fontSize: '0.75rem',
                                  fontWeight: 600,
                                  padding: '0.2rem 0.4rem',
                                  borderRadius: '4px',
                                  border: '1px solid #a7f3d0',
                                }}
                              >
                                {citation.verification_state.replace('_', ' ')}
                              </span>
                            </div>

                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                              <button
                                type="button"
                                data-testid={`inspect-details-btn-${citation.citation_id}`}
                                onClick={() => setExpandedCitationId(isExpanded ? null : citation.citation_id)}
                                style={{
                                  background: 'transparent',
                                  color: '#475569',
                                  border: '1px solid #cbd5e1',
                                  padding: '0.35rem 0.75rem',
                                  borderRadius: '4px',
                                  fontSize: '0.8rem',
                                  cursor: 'pointer',
                                  fontWeight: 500,
                                }}
                              >
                                {isExpanded ? 'Hide Details' : 'Inspect Details'}
                              </button>
                              <button
                                type="button"
                                data-testid={`download-doc-btn-${citation.citation_id}`}
                                onClick={() => handleDownloadDocument(citation.record_id, citation.citation_id, `${citation.label}.pdf`)}
                                disabled={isDownloading}
                                style={{
                                  background: '#0284c7',
                                  color: '#ffffff',
                                  border: 'none',
                                  padding: '0.35rem 0.75rem',
                                  borderRadius: '4px',
                                  fontSize: '0.8rem',
                                  cursor: isDownloading ? 'not-allowed' : 'pointer',
                                  opacity: isDownloading ? 0.7 : 1,
                                  fontWeight: 500,
                                }}
                              >
                                {isDownloading ? 'Downloading...' : 'Download Document'}
                              </button>
                            </div>
                          </div>

                          <div style={{ marginTop: '0.75rem', color: '#1e293b', fontWeight: 500, fontSize: '0.95rem' }}>
                            {citation.label}
                          </div>

                          {hasError && (
                            <div
                              data-testid={`download-error-${citation.citation_id}`}
                              style={{
                                marginTop: '0.5rem',
                                color: '#b91c1c',
                                fontSize: '0.85rem',
                                background: '#fef2f2',
                                padding: '0.4rem 0.6rem',
                                borderRadius: '4px',
                                border: '1px solid #fecaca',
                              }}
                            >
                              {downloadError.message}
                            </div>
                          )}

                          {isExpanded && (
                            <div
                              data-testid={`citation-details-${citation.citation_id}`}
                              style={{
                                marginTop: '0.75rem',
                                paddingTop: '0.75rem',
                                borderTop: '1px dashed #e2e8f0',
                                fontSize: '0.85rem',
                                color: '#64748b',
                                display: 'flex',
                                flexDirection: 'column',
                                gap: '0.25rem',
                              }}
                            >
                              <div><strong>Document Display:</strong> {citation.label}</div>
                              <div><strong>Canonical Record ID:</strong> <code style={{ color: '#0f172a' }}>{citation.record_id}</code></div>
                              <div><strong>Entity Type:</strong> {citation.entity_type}</div>
                              <div><strong>Verification State:</strong> {citation.verification_state}</div>
                            </div>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
