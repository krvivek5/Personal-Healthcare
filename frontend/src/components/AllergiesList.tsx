import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { allergiesApi, Allergy, AllergyCreate, AllergyUpdate, MedicalDocument } from '../lib/api'
import { ProvenanceBadge } from './ProvenanceBadge'

export const AllergiesList: React.FC<{ documents: MedicalDocument[], onViewDocument?: (id: string) => void }> = ({ documents, onViewDocument }) => {
  const { session } = useAuth()
  const [allergies, setAllergies] = useState<Allergy[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [allergen, setAllergen] = useState('')
  const [reaction, setReaction] = useState('')
  const [severity, setSeverity] = useState<'mild' | 'moderate' | 'severe' | 'life_threatening' | ''>('')
  const [sourceType, setSourceType] = useState('PATIENT_REPORTED')
  const [sourceId, setSourceId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editAllergen, setEditAllergen] = useState('')
  const [editReaction, setEditReaction] = useState('')
  const [editSeverity, setEditSeverity] = useState<'mild' | 'moderate' | 'severe' | 'life_threatening' | ''>('')

  useEffect(() => {
    if (!session?.access_token) return
    let mounted = true

    const fetchAllergies = async () => {
      try {
        const allgData = await allergiesApi.list(session.access_token)
        if (mounted) {
          setAllergies(allgData)
          setIsLoading(false)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load allergies')
          setIsLoading(false)
        }
      }
    }

    fetchAllergies()
    return () => { mounted = false }
  }, [session?.access_token])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session?.access_token || !allergen.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const payload: AllergyCreate = {
        allergen: allergen.trim(),
        reaction: reaction.trim() || null,
        severity: severity === '' ? null : severity,
        source_type: sourceType,
        source_id: sourceType === 'SOURCE_DOCUMENT' ? sourceId : null,
      }
      const newAllergy = await allergiesApi.create(session.access_token, payload)
      setAllergies([...allergies, newAllergy])
      setAllergen('')
      setReaction('')
      setSeverity('')
      setSourceType('PATIENT_REPORTED')
      setSourceId('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add allergy')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!session?.access_token) return

    try {
      await allergiesApi.delete(session.access_token, id)
      setAllergies(allergies.filter(a => a.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete allergy')
    }
  }

  const startEdit = (allergy: Allergy) => {
    setEditingId(allergy.id)
    setEditAllergen(allergy.allergen)
    setEditReaction(allergy.reaction || '')
    setEditSeverity(allergy.severity || '')
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token || !editAllergen.trim()) return

    try {
      const payload: AllergyUpdate = {
        allergen: editAllergen.trim(),
        reaction: editReaction.trim() || null,
        severity: editSeverity === '' ? null : editSeverity,
      }
      const updatedAllergy = await allergiesApi.update(session.access_token, id, payload)
      setAllergies(allergies.map(a => a.id === id ? updatedAllergy : a))
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update allergy')
    }
  }

  if (isLoading) return <div data-testid="allergies-loading">Loading allergies...</div>

  return (
    <div data-testid="allergies-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Allergies</h2>

      {error && <div data-testid="allergies-error" className="text-red-500 mb-4">{error}</div>}

      <form onSubmit={handleAdd} className="mb-6 flex gap-2 items-end flex-wrap">
        <div>
          <label className="block text-sm">Allergen</label>
          <input
            type="text"
            data-testid="input-allergy-allergen"
            value={allergen}
            onChange={(e) => setAllergen(e.target.value)}
            className="border p-2 rounded"
            required
          />
        </div>
        <div>
          <label className="block text-sm">Reaction</label>
          <input
            type="text"
            data-testid="input-allergy-reaction"
            value={reaction}
            onChange={(e) => setReaction(e.target.value)}
            className="border p-2 rounded"
          />
        </div>
        <div>
          <label className="block text-sm">Severity</label>
          <select
            data-testid="input-allergy-severity"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as 'mild' | 'moderate' | 'severe' | 'life_threatening' | '')}
            className="border p-2 rounded"
          >
            <option value="">None</option>
            <option value="mild">Mild</option>
            <option value="moderate">Moderate</option>
            <option value="severe">Severe</option>
            <option value="severe">Severe</option>
            <option value="life_threatening">Life Threatening</option>
          </select>
        </div>
        <div>
          <label className="block text-sm">Source Type</label>
          <select
            data-testid="input-allergy-source-type"
            value={sourceType}
            onChange={(e) => {
              setSourceType(e.target.value)
              if (e.target.value === 'PATIENT_REPORTED') setSourceId('')
            }}
            className="border p-2 rounded"
          >
            <option value="PATIENT_REPORTED">Patient Reported</option>
            <option value="SOURCE_DOCUMENT">Source Document</option>
          </select>
        </div>
        {sourceType === 'SOURCE_DOCUMENT' && (
          <div>
            <label className="block text-sm">Select Document</label>
            <select
              data-testid="input-allergy-source-id"
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              className="border p-2 rounded"
              required
            >
              <option value="">-- Choose --</option>
              {documents.map(d => (
                <option key={d.id} value={d.id}>{d.display_name}</option>
              ))}
            </select>
          </div>
        )}
        <button
          type="submit"
          data-testid="btn-add-allergy"
          disabled={isSubmitting}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          {isSubmitting ? 'Adding...' : 'Add'}
        </button>
      </form>

      {allergies.length === 0 ? (
        <p>No allergies recorded.</p>
      ) : (
        <ul className="space-y-2">
          {allergies.map((allergy) => (
            <li key={allergy.id} className="border p-3 rounded flex justify-between items-center" data-testid={`allergy-item-${allergy.id}`}>
              {editingId === allergy.id ? (
                <div className="flex gap-2 items-center flex-wrap">
                  <input
                    type="text"
                    data-testid={`edit-allergy-allergen-${allergy.id}`}
                    value={editAllergen}
                    onChange={(e) => setEditAllergen(e.target.value)}
                    className="border p-1 rounded"
                    required
                  />
                  <input
                    type="text"
                    data-testid={`edit-allergy-reaction-${allergy.id}`}
                    value={editReaction}
                    onChange={(e) => setEditReaction(e.target.value)}
                    className="border p-1 rounded"
                  />
                  <select
                    data-testid={`edit-allergy-severity-${allergy.id}`}
                    value={editSeverity}
                    onChange={(e) => setEditSeverity(e.target.value as 'mild' | 'moderate' | 'severe' | 'life_threatening' | '')}
                    className="border p-1 rounded"
                  >
                    <option value="">None</option>
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="severe">Severe</option>
                    <option value="life_threatening">Life Threatening</option>
                  </select>
                  <button
                    data-testid={`btn-save-allergy-${allergy.id}`}
                    onClick={() => handleUpdate(allergy.id)}
                    className="text-green-600 underline text-sm"
                  >
                    Save
                  </button>
                  <button
                    data-testid={`btn-cancel-allergy-${allergy.id}`}
                    onClick={cancelEdit}
                    className="text-gray-500 underline text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 items-center flex-wrap">
                  <span className="font-medium">{allergy.allergen}</span>
                  {allergy.reaction && (
                    <span className="text-sm text-gray-600">({allergy.reaction})</span>
                  )}
                  {allergy.severity && (
                    <span className="text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded">
                      {allergy.severity}
                    </span>
                  )}
                  <ProvenanceBadge
                    sourceType={allergy.source_type}
                    verificationState={allergy.verification_state}
                  />
                  {allergy.source_type === 'SOURCE_DOCUMENT' && allergy.source_id && (
                    <button
                      data-testid={`link-document-${allergy.source_id}`}
                      className="text-sm text-blue-600 underline"
                      onClick={() => onViewDocument && onViewDocument(allergy.source_id!)}
                    >
                      View Source
                    </button>
                  )}
                </div>
              )}

              {editingId !== allergy.id && (
                <div className="flex gap-2">
                  <button
                    data-testid={`btn-edit-allergy-${allergy.id}`}
                    onClick={() => startEdit(allergy)}
                    className="text-blue-500 underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    data-testid={`btn-delete-allergy-${allergy.id}`}
                    onClick={() => handleDelete(allergy.id)}
                    className="text-red-500 underline text-sm"
                  >
                    Delete
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
