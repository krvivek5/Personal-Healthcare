import React, { useEffect, useState, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { timelineApi, HealthEvent, HealthEventType, HealthEventState } from '../lib/api'

export const TimelineView: React.FC = () => {
  const { session } = useAuth()
  const [events, setEvents] = useState<HealthEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchTimeline = useCallback(async () => {
    if (!session?.access_token) return
    setIsLoading(true)
    setError(null)
    try {
      const data = await timelineApi.getTimeline(session.access_token)
      setEvents(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load health timeline')
    } finally {
      setIsLoading(false)
    }
  }, [session?.access_token])

  useEffect(() => {
    fetchTimeline()
  }, [fetchTimeline])

  const formatEventDate = (dateStr: string) => {
    if (!dateStr) return ''
    if (dateStr.includes('T')) {
      try {
        const d = new Date(dateStr)
        if (!isNaN(d.getTime())) {
          return d.toLocaleString(undefined, {
            timeZone: 'UTC',
            year: 'numeric',
            month: 'short',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            timeZoneName: 'short',
          })
        }
      } catch {
        // fallback to raw string
      }
    }
    return dateStr
  }

  const getEventTypeLabel = (type: HealthEventType | string): string => {
    switch (type) {
      case 'CONDITION_STARTED':
        return 'Condition Started'
      case 'CONDITION_RESOLVED':
        return 'Condition Resolved'
      case 'SYMPTOM_RECORDED':
        return 'Symptom Recorded'
      case 'MEDICATION_STARTED':
        return 'Medication Started'
      case 'MEDICATION_STOPPED':
        return 'Medication Stopped'
      case 'DOCUMENT_DATED':
        return 'Document Dated'
      case 'DOCUMENT_UPLOADED':
        return 'Document Uploaded'
      case 'GOAL_RECORDED':
        return 'Goal Recorded'
      default:
        return type.replace(/_/g, ' ')
    }
  }

  const getEventTypeBadgeStyle = (type: HealthEventType | string): React.CSSProperties => {
    switch (type) {
      case 'CONDITION_STARTED':
      case 'CONDITION_RESOLVED':
        return { backgroundColor: '#fef3c7', color: '#92400e', borderColor: '#fde68a' }
      case 'MEDICATION_STARTED':
      case 'MEDICATION_STOPPED':
        return { backgroundColor: '#e0e7ff', color: '#3730a3', borderColor: '#c7d2fe' }
      case 'SYMPTOM_RECORDED':
        return { backgroundColor: '#fee2e2', color: '#991b1b', borderColor: '#fecaca' }
      case 'DOCUMENT_DATED':
      case 'DOCUMENT_UPLOADED':
        return { backgroundColor: '#f3e8ff', color: '#6b21a8', borderColor: '#e9d5ff' }
      case 'GOAL_RECORDED':
        return { backgroundColor: '#ccfbf1', color: '#115e59', borderColor: '#99f6e4' }
      default:
        return { backgroundColor: '#f1f5f9', color: '#475569', borderColor: '#cbd5e1' }
    }
  }

  const getEventStateBadge = (state: HealthEventState) => {
    switch (state) {
      case 'current':
        return (
          <span
            data-testid="event-state"
            style={{
              backgroundColor: '#ecfdf5',
              color: '#065f46',
              border: '1px solid #a7f3d0',
              padding: '0.2rem 0.5rem',
              borderRadius: '9999px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            Current
          </span>
        )
      case 'historical':
        return (
          <span
            data-testid="event-state"
            style={{
              backgroundColor: '#f1f5f9',
              color: '#64748b',
              border: '1px solid #cbd5e1',
              padding: '0.2rem 0.5rem',
              borderRadius: '9999px',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            Historical
          </span>
        )
      case 'neutral':
      default:
        return (
          <span
            data-testid="event-state"
            style={{
              backgroundColor: '#f8fafc',
              color: '#475569',
              border: '1px solid #e2e8f0',
              padding: '0.2rem 0.5rem',
              borderRadius: '9999px',
              fontSize: '0.75rem',
              fontWeight: 500,
            }}
          >
            Observation
          </span>
        )
    }
  }

  const handleSourceClick = (sourceType: string, sourceId: string) => {
    // Scroll to the matching source element on the page if present
    const elementId = `${sourceType.toLowerCase()}-item-${sourceId}`
    const el = document.getElementById(elementId) || document.querySelector(`[data-testid="${elementId}"]`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      el.classList.add('highlight-target')
      setTimeout(() => el.classList.remove('highlight-target'), 2000)
    }
  }

  return (
    <div className="timeline-container card" data-testid="timeline-view" style={{ marginTop: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div>
          <h2 style={{ margin: 0 }}>Health Timeline</h2>
          <p style={{ color: '#64748b', fontSize: '0.9rem', margin: '0.25rem 0 0 0' }}>
            Chronological view of meaningful health events synthesized from your health records over time.
          </p>
        </div>
        <button
          data-testid="timeline-refresh-btn"
          onClick={fetchTimeline}
          disabled={isLoading}
          style={{
            background: '#f1f5f9',
            border: '1px solid #cbd5e1',
            padding: '0.4rem 0.8rem',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '0.85rem',
          }}
        >
          {isLoading ? 'Refreshing...' : 'Refresh Timeline'}
        </button>
      </div>

      {isLoading && (
        <div data-testid="timeline-loading" style={{ padding: '1.5rem', textAlign: 'center', color: '#64748b' }}>
          Loading health timeline...
        </div>
      )}

      {error && (
        <div
          data-testid="timeline-error"
          style={{
            background: '#fef2f2',
            color: '#b91c1c',
            padding: '1rem',
            borderRadius: '6px',
            border: '1px solid #fecaca',
            marginBottom: '1rem',
          }}
        >
          <span>{error}</span>
          <button
            onClick={fetchTimeline}
            style={{ marginLeft: '1rem', textDecoration: 'underline', background: 'none', border: 'none', cursor: 'pointer', color: '#b91c1c' }}
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !error && events.length === 0 && (
        <div
          data-testid="timeline-empty"
          style={{
            background: '#f8fafc',
            border: '1px dashed #cbd5e1',
            padding: '2rem',
            textAlign: 'center',
            borderRadius: '8px',
            color: '#64748b',
          }}
        >
          <p style={{ fontWeight: 500, margin: '0 0 0.5rem 0' }}>No health events recorded yet.</p>
          <p style={{ fontSize: '0.85rem', margin: 0 }}>
            As you log conditions, symptoms, medications, documents, or personal health goals, your longitudinal health story will appear here in chronological order.
          </p>
        </div>
      )}

      {!isLoading && !error && events.length > 0 && (
        <div className="timeline-list" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {events.map((event, index) => {
            const isHistorical = event.event_state === 'historical'
            return (
              <div
                key={`${event.source_type}-${event.source_id}-${event.event_type}-${index}`}
                data-testid="timeline-event"
                className={`timeline-event-card ${isHistorical ? 'timeline-event-historical' : ''}`}
                style={{
                  border: isHistorical ? '1px solid #e2e8f0' : '1px solid #cbd5e1',
                  borderRadius: '8px',
                  padding: '1rem',
                  backgroundColor: isHistorical ? '#fafafa' : '#ffffff',
                  opacity: isHistorical ? 0.85 : 1.0,
                  transition: 'all 0.2s ease',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '0.5rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <span
                      data-testid="event-type"
                      style={{
                        padding: '0.2rem 0.6rem',
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        border: '1px solid transparent',
                        ...getEventTypeBadgeStyle(event.event_type),
                      }}
                    >
                      {getEventTypeLabel(event.event_type)}
                    </span>
                    {getEventStateBadge(event.event_state)}
                    <span
                      data-testid="event-date"
                      style={{ color: '#475569', fontSize: '0.85rem', fontWeight: 500 }}
                    >
                      {formatEventDate(event.event_date)}
                    </span>
                  </div>

                  <button
                    data-testid="event-source-link"
                    onClick={() => handleSourceClick(event.source_type, event.source_id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#0284c7',
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                      padding: 0,
                      textDecoration: 'underline',
                    }}
                    title={`View source ${event.source_type} (${event.source_id})`}
                  >
                    Source: {event.source_type}
                  </button>
                </div>

                <div style={{ marginTop: '0.5rem' }}>
                  <div data-testid="event-title" style={{ fontWeight: 600, fontSize: '1rem', color: '#1e293b' }}>
                    {event.title}
                  </div>
                  {event.description && (
                    <div
                      data-testid="event-description"
                      style={{ color: '#64748b', fontSize: '0.85rem', marginTop: '0.25rem', whiteSpace: 'pre-line' }}
                    >
                      {event.description}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
