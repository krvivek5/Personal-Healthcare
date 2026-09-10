import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HealthProfileView } from './HealthProfileView'
import { healthProfileApi } from '../lib/api'
import { useAuth } from '../context/AuthContext'

vi.mock('../lib/api', () => ({
  healthProfileApi: {
    get: vi.fn(),
    update: vi.fn(),
  },
}))

vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

describe('HealthProfileView', () => {
  const mockToken = 'mock-token'

  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  it('renders loading state initially and then empty profile correctly', async () => {
    vi.mocked(healthProfileApi.get).mockResolvedValueOnce({
      id: 'hp-1',
      patient_id: 'p-1',
      date_of_birth: null,
      biological_sex: null,
      height_cm: null,
      blood_group: null,
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    render(<HealthProfileView />)

    expect(screen.getByTestId('health-profile-loading')).toBeInTheDocument()

    await waitFor(() => {
      expect(screen.queryByTestId('health-profile-loading')).not.toBeInTheDocument()
    })

    expect(screen.getByTestId('health-profile-view')).toBeInTheDocument()
    expect(screen.getByTestId('input-dob')).toHaveValue('')
    expect(screen.getByTestId('input-sex')).toHaveValue('')
    expect(screen.getByTestId('input-blood')).toHaveValue('')
    expect(screen.getByTestId('input-height')).toHaveValue(null)
  })

  it('populates existing profile values correctly', async () => {
    vi.mocked(healthProfileApi.get).mockResolvedValueOnce({
      id: 'hp-1',
      patient_id: 'p-1',
      date_of_birth: '1990-01-01',
      biological_sex: 'Female',
      height_cm: 165.5,
      blood_group: 'A+',
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    render(<HealthProfileView />)

    await waitFor(() => {
      expect(screen.queryByTestId('health-profile-loading')).not.toBeInTheDocument()
    })

    expect(screen.getByTestId('input-dob')).toHaveValue('1990-01-01')
    expect(screen.getByTestId('input-sex')).toHaveValue('Female')
    expect(screen.getByTestId('input-blood')).toHaveValue('A+')
    expect(screen.getByTestId('input-height')).toHaveValue(165.5)
  })

  it('shows saving state, calls API with expected payload, and reflects updated state on save', async () => {
    vi.mocked(healthProfileApi.get).mockResolvedValueOnce({
      id: 'hp-1',
      patient_id: 'p-1',
      date_of_birth: null,
      biological_sex: null,
      height_cm: null,
      blood_group: null,
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    vi.mocked(healthProfileApi.update).mockImplementationOnce(async () => {
      // simulate network delay to test loading state
      await new Promise(resolve => setTimeout(resolve, 50))
      return {
        id: 'hp-1',
        patient_id: 'p-1',
        date_of_birth: '1985-05-15',
        biological_sex: 'Male',
        height_cm: 180,
        blood_group: 'O-',
        notes: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }
    })

    render(<HealthProfileView />)

    await waitFor(() => {
      expect(screen.queryByTestId('health-profile-loading')).not.toBeInTheDocument()
    })

    fireEvent.change(screen.getByTestId('input-dob'), { target: { value: '1985-05-15' } })
    fireEvent.change(screen.getByTestId('input-sex'), { target: { value: 'Male' } })
    fireEvent.change(screen.getByTestId('input-blood'), { target: { value: 'O-' } })
    fireEvent.change(screen.getByTestId('input-height'), { target: { value: '180' } })

    const saveButton = screen.getByTestId('btn-save-profile')
    fireEvent.click(saveButton)

    // Verify saving state
    expect(saveButton).toBeDisabled()
    expect(saveButton).toHaveTextContent('Saving...')

    // Verify API called with correct payload
    expect(healthProfileApi.update).toHaveBeenCalledWith(mockToken, {
      date_of_birth: '1985-05-15',
      biological_sex: 'Male',
      blood_group: 'O-',
      height_cm: 180,
    })

    // Wait for save to complete
    await waitFor(() => {
      expect(saveButton).not.toBeDisabled()
      expect(saveButton).toHaveTextContent('Save Profile')
    })
    
    // Values should remain after save
    expect(screen.getByTestId('input-dob')).toHaveValue('1985-05-15')
    expect(screen.getByTestId('input-sex')).toHaveValue('Male')
    expect(screen.getByTestId('input-blood')).toHaveValue('O-')
    expect(screen.getByTestId('input-height')).toHaveValue(180)
  })

  it('shows error on API failure without silently discarding entered values', async () => {
    vi.mocked(healthProfileApi.get).mockResolvedValueOnce({
      id: 'hp-1',
      patient_id: 'p-1',
      date_of_birth: null,
      biological_sex: null,
      height_cm: null,
      blood_group: null,
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })

    vi.mocked(healthProfileApi.update).mockRejectedValueOnce(new Error('Update failed'))

    render(<HealthProfileView />)

    await waitFor(() => {
      expect(screen.queryByTestId('health-profile-loading')).not.toBeInTheDocument()
    })

    fireEvent.change(screen.getByTestId('input-sex'), { target: { value: 'Female' } })

    fireEvent.click(screen.getByTestId('btn-save-profile'))

    await waitFor(() => {
      expect(screen.getByTestId('health-profile-error')).toHaveTextContent('Update failed')
    })

    // Value should still be there
    expect(screen.getByTestId('input-sex')).toHaveValue('Female')
  })
})
