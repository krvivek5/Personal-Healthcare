import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuth } from '../context/AuthContext'
import { timelineApi, HealthEvent } from '../lib/api'
import { TimelineView } from './TimelineView'

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  timelineApi: {
    getTimeline: vi.fn(),
  },
}))

const mockToken = 'mock-token'

const mockEvents: HealthEvent[] = [
  {
    event_date: '2026-05-20',
    event_type: 'DOCUMENT_DATED',
    event_state: 'neutral',
    title: 'Lab Blood Work Report',
    description: 'Comprehensive Metabolic Panel',
    source_type: 'DOCUMENT',
    source_id: 'doc-uuid-1',
  },
  {
    event_date: '2026-04-10T14:30:00Z',
    event_type: 'GOAL_RECORDED',
    event_state: 'current',
    title: 'Walk 10,000 steps daily',
    description: 'Tracked with pedometer',
    source_type: 'GOAL',
    source_id: 'goal-uuid-1',
  },
  {
    event_date: '2026-03-15',
    event_type: 'MEDICATION_STARTED',
    event_state: 'current',
    title: 'Lisinopril 10mg',
    description: 'Dosage: 10mg | Frequency: Once daily',
    source_type: 'MEDICATION',
    source_id: 'med-uuid-1',
  },
  {
    event_date: '2026-02-01T08:15:00Z',
    event_type: 'SYMPTOM_RECORDED',
    event_state: 'neutral',
    title: 'Throbbing Headache',
    description: 'Severity: moderate | Located in temples',
    source_type: 'SYMPTOM',
    source_id: 'symp-uuid-1',
  },
  {
    event_date: '2026-01-05',
    event_type: 'CONDITION_STARTED',
    event_state: 'current',
    title: 'Hypertension Stage 1',
    description: 'Diagnosed by primary care physician',
    source_type: 'CONDITION',
    source_id: 'cond-uuid-1',
  },
  {
    event_date: '2025-11-20',
    event_type: 'CONDITION_RESOLVED',
    event_state: 'historical',
    title: 'Acute Bronchitis (Resolved)',
    description: 'Completed antibiotics course',
    source_type: 'CONDITION',
    source_id: 'cond-uuid-2',
  },
]

describe('TimelineView', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('shows loading state initially', () => {
    vi.mocked(timelineApi.getTimeline).mockReturnValue(new Promise(() => {}))
    render(<TimelineView />)
    expect(screen.getByTestId('timeline-loading')).toBeInTheDocument()
    expect(timelineApi.getTimeline).toHaveBeenCalledWith(mockToken)
  })

  it('shows empty state when no events exist', async () => {
    vi.mocked(timelineApi.getTimeline).mockResolvedValueOnce([])
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getByTestId('timeline-empty')).toBeInTheDocument()
    })
    expect(screen.getByText(/No health events recorded yet/i)).toBeInTheDocument()
  })

  it('shows error state when API fails, and allows retry', async () => {
    vi.mocked(timelineApi.getTimeline).mockRejectedValueOnce(new Error('Network error'))
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getByTestId('timeline-error')).toBeInTheDocument()
    })
    expect(screen.getByText(/Network error/i)).toBeInTheDocument()

    // Retry
    vi.mocked(timelineApi.getTimeline).mockResolvedValueOnce(mockEvents)
    fireEvent.click(screen.getByText('Retry'))

    await waitFor(() => {
      expect(screen.queryByTestId('timeline-error')).not.toBeInTheDocument()
      expect(screen.getAllByTestId('timeline-event')).toHaveLength(mockEvents.length)
    })
  })

  it('renders chronological timeline events with all source types and event types', async () => {
    vi.mocked(timelineApi.getTimeline).mockResolvedValueOnce(mockEvents)
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getAllByTestId('timeline-event')).toHaveLength(6)
    })

    // Verify ordering is maintained (newest first)
    const titles = screen.getAllByTestId('event-title').map((el) => el.textContent)
    expect(titles[0]).toBe('Lab Blood Work Report')
    expect(titles[1]).toBe('Walk 10,000 steps daily')
    expect(titles[2]).toBe('Lisinopril 10mg')
    expect(titles[3]).toBe('Throbbing Headache')
    expect(titles[4]).toBe('Hypertension Stage 1')
    expect(titles[5]).toBe('Acute Bronchitis (Resolved)')

    // Verify event_type labels
    const typeBadges = screen.getAllByTestId('event-type').map((el) => el.textContent)
    expect(typeBadges).toContain('Document Dated')
    expect(typeBadges).toContain('Goal Recorded')
    expect(typeBadges).toContain('Medication Started')
    expect(typeBadges).toContain('Symptom Recorded')
    expect(typeBadges).toContain('Condition Started')
    expect(typeBadges).toContain('Condition Resolved')
  })

  it('renders clear visual distinction between current, historical, and neutral event states', async () => {
    vi.mocked(timelineApi.getTimeline).mockResolvedValueOnce(mockEvents)
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getAllByTestId('timeline-event')).toHaveLength(6)
    })

    const stateBadges = screen.getAllByTestId('event-state').map((el) => el.textContent)
    expect(stateBadges.filter((s) => s === 'Current').length).toBe(3)
    expect(stateBadges.filter((s) => s === 'Historical').length).toBe(1)
    expect(stateBadges.filter((s) => s === 'Observation').length).toBe(2)
  })

  it('renders source links with source_type and handles source navigation', async () => {
    vi.mocked(timelineApi.getTimeline).mockResolvedValueOnce(mockEvents)
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getAllByTestId('timeline-event')).toHaveLength(6)
    })

    const sourceLinks = screen.getAllByTestId('event-source-link')
    expect(sourceLinks[0]).toHaveTextContent('Source: DOCUMENT')
    expect(sourceLinks[1]).toHaveTextContent('Source: GOAL')
    expect(sourceLinks[2]).toHaveTextContent('Source: MEDICATION')
    expect(sourceLinks[3]).toHaveTextContent('Source: SYMPTOM')
    expect(sourceLinks[4]).toHaveTextContent('Source: CONDITION')

    // Clicking source link does not throw
    fireEvent.click(sourceLinks[0])
  })

  it('allows manual refresh via refresh button', async () => {
    vi.mocked(timelineApi.getTimeline).mockResolvedValue(mockEvents)
    render(<TimelineView />)

    await waitFor(() => {
      expect(screen.getAllByTestId('timeline-event')).toHaveLength(6)
    })

    fireEvent.click(screen.getByTestId('timeline-refresh-btn'))
    await waitFor(() => {
      expect(timelineApi.getTimeline).toHaveBeenCalledTimes(2)
    })
  })
})
