import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useAuth } from '../context/AuthContext'
import {
  conditionsApi,
  symptomsApi,
  medicationsApi,
  allergiesApi,
  goalsApi
} from '../lib/api'

import { ConditionsList } from './ConditionsList'
import { SymptomsList } from './SymptomsList'
import { MedicationsList } from './MedicationsList'
import { AllergiesList } from './AllergiesList'
import { GoalsList } from './GoalsList'

// Mock the AuthContext
vi.mock('../context/AuthContext', () => ({
  useAuth: vi.fn(),
}))

// Mock all API clients
vi.mock('../lib/api', () => ({
  conditionsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  symptomsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  medicationsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  allergiesApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
  goalsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

describe('Clinical Entity Lists', () => {
  const mockToken = 'mock-token'

  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(useAuth).mockReturnValue({
      session: { access_token: mockToken },
    } as unknown as ReturnType<typeof useAuth>)
  })

  // ---------------------------------------------------------------------------
  // Conditions
  // ---------------------------------------------------------------------------
  describe('ConditionsList', () => {
    const mockCondition = {
      id: 'cond-1',
      patient_id: 'p-1',
      name: 'Hypertension',
      status: 'active' as const,
      is_chronic: true,
      started_at: null,
      ended_at: null,
      recorded_at: '2026-01-01T00:00:00Z',
      notes: null,
      source_type: 'PATIENT_REPORTED',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    it('loads and views conditions', async () => {
      vi.mocked(conditionsApi.list).mockResolvedValueOnce([mockCondition])
      render(<ConditionsList />)
      
      expect(screen.getByTestId('conditions-loading')).toBeInTheDocument()
      await waitFor(() => expect(screen.queryByTestId('conditions-loading')).not.toBeInTheDocument())
      
      expect(screen.getByText('Hypertension')).toBeInTheDocument()
      expect(screen.getByText('Active')).toBeInTheDocument() // The text might be lowercase or capitalized depending on how it's rendered, wait, we rendered `{condition.status}` so it will be `active`. Wait, the render says `{condition.status}`.
      expect(conditionsApi.list).toHaveBeenCalledWith(mockToken)
    })

    it('creates a new condition', async () => {
      vi.mocked(conditionsApi.list).mockResolvedValueOnce([])
      const newCond = { ...mockCondition, id: 'cond-2', name: 'Asthma' }
      vi.mocked(conditionsApi.create).mockResolvedValueOnce(newCond)
      
      render(<ConditionsList />)
      await waitFor(() => expect(screen.queryByTestId('conditions-loading')).not.toBeInTheDocument())
      
      fireEvent.change(screen.getByTestId('input-condition-name'), { target: { value: 'Asthma' } })
      fireEvent.click(screen.getByTestId('btn-add-condition'))
      
      await waitFor(() => {
        expect(conditionsApi.create).toHaveBeenCalledWith(mockToken, {
          name: 'Asthma',
          status: 'active',
          is_chronic: false
        })
      })
      expect(screen.getByText('Asthma')).toBeInTheDocument()
      
      // Ensure source_type is absent from the payload!
      const callArg = vi.mocked(conditionsApi.create).mock.calls[0][1]
      expect(callArg).not.toHaveProperty('source_type')
    })

    it('edits a condition', async () => {
      vi.mocked(conditionsApi.list).mockResolvedValueOnce([mockCondition])
      const updatedCond = { ...mockCondition, status: 'resolved' as const }
      vi.mocked(conditionsApi.update).mockResolvedValueOnce(updatedCond)
      
      render(<ConditionsList />)
      await waitFor(() => expect(screen.queryByTestId('conditions-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-edit-condition-${mockCondition.id}`))
      
      fireEvent.change(screen.getByTestId(`edit-condition-status-${mockCondition.id}`), { target: { value: 'resolved' } })
      fireEvent.click(screen.getByTestId(`btn-save-condition-${mockCondition.id}`))
      
      await waitFor(() => {
        expect(conditionsApi.update).toHaveBeenCalledWith(mockToken, mockCondition.id, {
          status: 'resolved',
          is_chronic: true
        })
      })
      
      const updateCallArg = vi.mocked(conditionsApi.update).mock.calls[0][2]
      expect(updateCallArg).not.toHaveProperty('source_type')
    })

    it('deletes a condition', async () => {
      vi.mocked(conditionsApi.list).mockResolvedValueOnce([mockCondition])
      vi.mocked(conditionsApi.delete).mockResolvedValueOnce(undefined)
      
      render(<ConditionsList />)
      await waitFor(() => expect(screen.queryByTestId('conditions-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-delete-condition-${mockCondition.id}`))
      
      await waitFor(() => {
        expect(conditionsApi.delete).toHaveBeenCalledWith(mockToken, mockCondition.id)
      })
      expect(screen.queryByText('Hypertension')).not.toBeInTheDocument()
    })
  })

  // ---------------------------------------------------------------------------
  // Symptoms
  // ---------------------------------------------------------------------------
  describe('SymptomsList', () => {
    const mockSymptom = {
      id: 'sym-1',
      patient_id: 'p-1',
      name: 'Headache',
      severity: 'mild' as const,
      started_at: null,
      ended_at: null,
      recorded_at: '2026-01-01T00:00:00Z',
      notes: null,
      source_type: 'PATIENT_REPORTED',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    it('loads and views symptoms', async () => {
      vi.mocked(symptomsApi.list).mockResolvedValueOnce([mockSymptom])
      render(<SymptomsList />)
      
      await waitFor(() => expect(screen.queryByTestId('symptoms-loading')).not.toBeInTheDocument())
      expect(screen.getByText('Headache')).toBeInTheDocument()
    })

    it('creates a new symptom', async () => {
      vi.mocked(symptomsApi.list).mockResolvedValueOnce([])
      const newSym = { ...mockSymptom, id: 'sym-2', name: 'Fever', severity: 'severe' as const }
      vi.mocked(symptomsApi.create).mockResolvedValueOnce(newSym)
      
      render(<SymptomsList />)
      await waitFor(() => expect(screen.queryByTestId('symptoms-loading')).not.toBeInTheDocument())
      
      fireEvent.change(screen.getByTestId('input-symptom-name'), { target: { value: 'Fever' } })
      fireEvent.change(screen.getByTestId('input-symptom-severity'), { target: { value: 'severe' } })
      fireEvent.click(screen.getByTestId('btn-add-symptom'))
      
      await waitFor(() => {
        expect(symptomsApi.create).toHaveBeenCalledWith(mockToken, {
          name: 'Fever',
          severity: 'severe'
        })
      })
      
      const callArg = vi.mocked(symptomsApi.create).mock.calls[0][1]
      expect(callArg).not.toHaveProperty('source_type')
    })

    it('edits a symptom', async () => {
      vi.mocked(symptomsApi.list).mockResolvedValueOnce([mockSymptom])
      const updatedSym = { ...mockSymptom, severity: 'moderate' as const }
      vi.mocked(symptomsApi.update).mockResolvedValueOnce(updatedSym)
      
      render(<SymptomsList />)
      await waitFor(() => expect(screen.queryByTestId('symptoms-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-edit-symptom-${mockSymptom.id}`))
      
      fireEvent.change(screen.getByTestId(`edit-symptom-severity-${mockSymptom.id}`), { target: { value: 'moderate' } })
      fireEvent.click(screen.getByTestId(`btn-save-symptom-${mockSymptom.id}`))
      
      await waitFor(() => {
        expect(symptomsApi.update).toHaveBeenCalledWith(mockToken, mockSymptom.id, {
          name: 'Headache',
          severity: 'moderate'
        })
      })
      
      const updateCallArg = vi.mocked(symptomsApi.update).mock.calls[0][2]
      expect(updateCallArg).not.toHaveProperty('source_type')
    })

    it('deletes a symptom', async () => {
      vi.mocked(symptomsApi.list).mockResolvedValueOnce([mockSymptom])
      vi.mocked(symptomsApi.delete).mockResolvedValueOnce(undefined)
      
      render(<SymptomsList />)
      await waitFor(() => expect(screen.queryByTestId('symptoms-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-delete-symptom-${mockSymptom.id}`))
      
      await waitFor(() => {
        expect(symptomsApi.delete).toHaveBeenCalledWith(mockToken, mockSymptom.id)
      })
    })
  })

  // ---------------------------------------------------------------------------
  // Medications
  // ---------------------------------------------------------------------------
  describe('MedicationsList', () => {
    const mockMed = {
      id: 'med-1',
      patient_id: 'p-1',
      name: 'Ibuprofen',
      dosage: '200mg',
      frequency: 'Every 8 hours',
      status: 'active' as const,
      as_needed: true,
      started_at: null,
      ended_at: null,
      recorded_at: '2026-01-01T00:00:00Z',
      notes: null,
      source_type: 'PATIENT_REPORTED',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    it('loads and views medications', async () => {
      vi.mocked(medicationsApi.list).mockResolvedValueOnce([mockMed])
      render(<MedicationsList />)
      await waitFor(() => expect(screen.queryByTestId('medications-loading')).not.toBeInTheDocument())
      expect(screen.getByText('Ibuprofen')).toBeInTheDocument()
    })

    it('creates a new medication', async () => {
      vi.mocked(medicationsApi.list).mockResolvedValueOnce([])
      const newMed = { ...mockMed, id: 'med-2', name: 'Aspirin' }
      vi.mocked(medicationsApi.create).mockResolvedValueOnce(newMed)
      
      render(<MedicationsList />)
      await waitFor(() => expect(screen.queryByTestId('medications-loading')).not.toBeInTheDocument())
      
      fireEvent.change(screen.getByTestId('input-med-name'), { target: { value: 'Aspirin' } })
      fireEvent.change(screen.getByTestId('input-med-dosage'), { target: { value: '81mg' } })
      fireEvent.click(screen.getByTestId('btn-add-med'))
      
      await waitFor(() => {
        expect(medicationsApi.create).toHaveBeenCalledWith(mockToken, {
          name: 'Aspirin',
          dosage: '81mg',
          frequency: null,
          status: 'active',
          as_needed: false
        })
      })
      
      const callArg = vi.mocked(medicationsApi.create).mock.calls[0][1]
      expect(callArg).not.toHaveProperty('source_type')
    })

    it('edits a medication', async () => {
      vi.mocked(medicationsApi.list).mockResolvedValueOnce([mockMed])
      const updatedMed = { ...mockMed, status: 'stopped' as const }
      vi.mocked(medicationsApi.update).mockResolvedValueOnce(updatedMed)
      
      render(<MedicationsList />)
      await waitFor(() => expect(screen.queryByTestId('medications-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-edit-med-${mockMed.id}`))
      
      fireEvent.change(screen.getByTestId(`edit-med-status-${mockMed.id}`), { target: { value: 'stopped' } })
      fireEvent.click(screen.getByTestId(`btn-save-med-${mockMed.id}`))
      
      await waitFor(() => {
        expect(medicationsApi.update).toHaveBeenCalledWith(mockToken, mockMed.id, {
          name: 'Ibuprofen',
          dosage: '200mg',
          frequency: 'Every 8 hours',
          status: 'stopped',
          as_needed: true
        })
      })
      
      const updateCallArg = vi.mocked(medicationsApi.update).mock.calls[0][2]
      expect(updateCallArg).not.toHaveProperty('source_type')
    })

    it('deletes a medication', async () => {
      vi.mocked(medicationsApi.list).mockResolvedValueOnce([mockMed])
      vi.mocked(medicationsApi.delete).mockResolvedValueOnce(undefined)
      
      render(<MedicationsList />)
      await waitFor(() => expect(screen.queryByTestId('medications-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-delete-med-${mockMed.id}`))
      
      await waitFor(() => {
        expect(medicationsApi.delete).toHaveBeenCalledWith(mockToken, mockMed.id)
      })
    })
  })

  // ---------------------------------------------------------------------------
  // Allergies
  // ---------------------------------------------------------------------------
  describe('AllergiesList', () => {
    const mockAllergy = {
      id: 'alg-1',
      patient_id: 'p-1',
      allergen: 'Peanuts',
      reaction: 'Hives',
      severity: 'severe' as const,
      recorded_at: '2026-01-01T00:00:00Z',
      notes: null,
      source_type: 'PATIENT_REPORTED',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    it('loads and views allergies', async () => {
      vi.mocked(allergiesApi.list).mockResolvedValueOnce([mockAllergy])
      render(<AllergiesList />)
      await waitFor(() => expect(screen.queryByTestId('allergies-loading')).not.toBeInTheDocument())
      expect(screen.getByText('Peanuts')).toBeInTheDocument()
    })

    it('creates a new allergy', async () => {
      vi.mocked(allergiesApi.list).mockResolvedValueOnce([])
      const newAlg = { ...mockAllergy, id: 'alg-2', allergen: 'Dust' }
      vi.mocked(allergiesApi.create).mockResolvedValueOnce(newAlg)
      
      render(<AllergiesList />)
      await waitFor(() => expect(screen.queryByTestId('allergies-loading')).not.toBeInTheDocument())
      
      fireEvent.change(screen.getByTestId('input-allergy-allergen'), { target: { value: 'Dust' } })
      fireEvent.click(screen.getByTestId('btn-add-allergy'))
      
      await waitFor(() => {
        expect(allergiesApi.create).toHaveBeenCalledWith(mockToken, {
          allergen: 'Dust',
          reaction: null,
          severity: null
        })
      })
      
      const callArg = vi.mocked(allergiesApi.create).mock.calls[0][1]
      expect(callArg).not.toHaveProperty('source_type')
    })

    it('edits an allergy', async () => {
      vi.mocked(allergiesApi.list).mockResolvedValueOnce([mockAllergy])
      const updatedAlg = { ...mockAllergy, severity: 'life_threatening' as const }
      vi.mocked(allergiesApi.update).mockResolvedValueOnce(updatedAlg)
      
      render(<AllergiesList />)
      await waitFor(() => expect(screen.queryByTestId('allergies-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-edit-allergy-${mockAllergy.id}`))
      
      fireEvent.change(screen.getByTestId(`edit-allergy-severity-${mockAllergy.id}`), { target: { value: 'life_threatening' } })
      fireEvent.click(screen.getByTestId(`btn-save-allergy-${mockAllergy.id}`))
      
      await waitFor(() => {
        expect(allergiesApi.update).toHaveBeenCalledWith(mockToken, mockAllergy.id, {
          allergen: 'Peanuts',
          reaction: 'Hives',
          severity: 'life_threatening'
        })
      })
      
      const updateCallArg = vi.mocked(allergiesApi.update).mock.calls[0][2]
      expect(updateCallArg).not.toHaveProperty('source_type')
    })

    it('deletes an allergy', async () => {
      vi.mocked(allergiesApi.list).mockResolvedValueOnce([mockAllergy])
      vi.mocked(allergiesApi.delete).mockResolvedValueOnce(undefined)
      
      render(<AllergiesList />)
      await waitFor(() => expect(screen.queryByTestId('allergies-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-delete-allergy-${mockAllergy.id}`))
      
      await waitFor(() => {
        expect(allergiesApi.delete).toHaveBeenCalledWith(mockToken, mockAllergy.id)
      })
    })
  })

  // ---------------------------------------------------------------------------
  // Goals
  // ---------------------------------------------------------------------------
  describe('GoalsList', () => {
    const mockGoal = {
      id: 'gol-1',
      patient_id: 'p-1',
      description: 'Exercise daily',
      status: 'active' as const,
      target_date: '2026-12-31',
      recorded_at: '2026-01-01T00:00:00Z',
      notes: null,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    }

    it('loads and views goals', async () => {
      vi.mocked(goalsApi.list).mockResolvedValueOnce([mockGoal])
      render(<GoalsList />)
      await waitFor(() => expect(screen.queryByTestId('goals-loading')).not.toBeInTheDocument())
      expect(screen.getByText('Exercise daily')).toBeInTheDocument()
    })

    it('creates a new goal', async () => {
      vi.mocked(goalsApi.list).mockResolvedValueOnce([])
      const newGoal = { ...mockGoal, id: 'gol-2', description: 'Drink water' }
      vi.mocked(goalsApi.create).mockResolvedValueOnce(newGoal)
      
      render(<GoalsList />)
      await waitFor(() => expect(screen.queryByTestId('goals-loading')).not.toBeInTheDocument())
      
      fireEvent.change(screen.getByTestId('input-goal-description'), { target: { value: 'Drink water' } })
      fireEvent.click(screen.getByTestId('btn-add-goal'))
      
      await waitFor(() => {
        expect(goalsApi.create).toHaveBeenCalledWith(mockToken, {
          description: 'Drink water',
          status: 'active',
          target_date: null
        })
      })
      
      const callArg = vi.mocked(goalsApi.create).mock.calls[0][1]
      expect(callArg).not.toHaveProperty('source_type')
    })

    it('edits a goal', async () => {
      vi.mocked(goalsApi.list).mockResolvedValueOnce([mockGoal])
      const updatedGoal = { ...mockGoal, status: 'achieved' as const }
      vi.mocked(goalsApi.update).mockResolvedValueOnce(updatedGoal)
      
      render(<GoalsList />)
      await waitFor(() => expect(screen.queryByTestId('goals-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-edit-goal-${mockGoal.id}`))
      
      fireEvent.change(screen.getByTestId(`edit-goal-status-${mockGoal.id}`), { target: { value: 'achieved' } })
      fireEvent.click(screen.getByTestId(`btn-save-goal-${mockGoal.id}`))
      
      await waitFor(() => {
        expect(goalsApi.update).toHaveBeenCalledWith(mockToken, mockGoal.id, {
          description: 'Exercise daily',
          status: 'achieved',
          target_date: '2026-12-31'
        })
      })
      
      const updateCallArg = vi.mocked(goalsApi.update).mock.calls[0][2]
      expect(updateCallArg).not.toHaveProperty('source_type')
    })

    it('deletes a goal', async () => {
      vi.mocked(goalsApi.list).mockResolvedValueOnce([mockGoal])
      vi.mocked(goalsApi.delete).mockResolvedValueOnce(undefined)
      
      render(<GoalsList />)
      await waitFor(() => expect(screen.queryByTestId('goals-loading')).not.toBeInTheDocument())
      
      fireEvent.click(screen.getByTestId(`btn-delete-goal-${mockGoal.id}`))
      
      await waitFor(() => {
        expect(goalsApi.delete).toHaveBeenCalledWith(mockToken, mockGoal.id)
      })
    })
  })
})
