import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { symptomsApi, Symptom, SymptomCreate, SymptomUpdate, MedicalDocument } from '../lib/api'
import { ProvenanceBadge } from './ProvenanceBadge'

export const SymptomsList: React.FC<{ documents: MedicalDocument[], onViewDocument?: (id: string) => void }> = ({ documents, onViewDocument }) => {
  const { session } = useAuth()
  const [symptoms, setSymptoms] = useState<Symptom[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [severity, setSeverity] = useState<'mild' | 'moderate' | 'severe' | ''>('')
  const [sourceType, setSourceType] = useState('PATIENT_REPORTED')
  const [sourceId, setSourceId] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editSeverity, setEditSeverity] = useState<'mild' | 'moderate' | 'severe' | ''>('')

  useEffect(() => {
    if (!session?.access_token) return
    let mounted = true

    const fetchSymptoms = async () => {
      try {
        const symData = await symptomsApi.list(session.access_token)
        if (mounted) {
          setSymptoms(symData)
          setIsLoading(false)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load symptoms')
          setIsLoading(false)
        }
      }
    }

    fetchSymptoms()
    return () => { mounted = false }
  }, [session?.access_token])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session?.access_token || !name.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const payload: SymptomCreate = {
        name: name.trim(),
        severity: severity === '' ? null : severity,
        source_type: sourceType,
        source_id: sourceType === 'SOURCE_DOCUMENT' ? sourceId : null,
      }
      const newSymptom = await symptomsApi.create(session.access_token, payload)
      setSymptoms([...symptoms, newSymptom])
      setName('')
      setSeverity('')
      setSourceType('PATIENT_REPORTED')
      setSourceId('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add symptom')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!session?.access_token) return

    try {
      await symptomsApi.delete(session.access_token, id)
      setSymptoms(symptoms.filter(s => s.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete symptom')
    }
  }

  const startEdit = (symptom: Symptom) => {
    setEditingId(symptom.id)
    setEditName(symptom.name)
    setEditSeverity(symptom.severity || '')
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token || !editName.trim()) return

    try {
      const payload: SymptomUpdate = {
        name: editName.trim(),
        severity: editSeverity === '' ? null : editSeverity,
      }
      const updatedSymptom = await symptomsApi.update(session.access_token, id, payload)
      setSymptoms(symptoms.map(s => s.id === id ? updatedSymptom : s))
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update symptom')
    }
  }

  if (isLoading) return <div data-testid="symptoms-loading">Loading symptoms...</div>

  return (
    <div data-testid="symptoms-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Symptoms</h2>

      {error && <div data-testid="symptoms-error" className="text-red-500 mb-4">{error}</div>}

      <form onSubmit={handleAdd} className="mb-6 flex gap-2 items-end">
        <div>
          <label className="block text-sm">Symptom Name</label>
          <input
            type="text"
            data-testid="input-symptom-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border p-2 rounded"
            required
          />
        </div>
        <div>
          <label className="block text-sm">Severity</label>
          <select
            data-testid="input-symptom-severity"
            value={severity}
            onChange={(e) => setSeverity(e.target.value as 'mild' | 'moderate' | 'severe' | '')}
            className="border p-2 rounded"
          >
            <option value="">None</option>
            <option value="mild">Mild</option>
            <option value="moderate">Moderate</option>
            <option value="severe">Severe</option>
          </select>
        </div>
        <div>
          <label className="block text-sm">Source Type</label>
          <select
            data-testid="input-symptom-source-type"
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
              data-testid="input-symptom-source-id"
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
          data-testid="btn-add-symptom"
          disabled={isSubmitting}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          {isSubmitting ? 'Adding...' : 'Add'}
        </button>
      </form>

      {symptoms.length === 0 ? (
        <p>No symptoms recorded.</p>
      ) : (
        <ul className="space-y-2">
          {symptoms.map((symptom) => (
            <li key={symptom.id} className="border p-3 rounded flex justify-between items-center" data-testid={`symptom-item-${symptom.id}`}>
              {editingId === symptom.id ? (
                <div className="flex gap-2 items-center">
                  <input
                    type="text"
                    data-testid={`edit-symptom-name-${symptom.id}`}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="border p-1 rounded"
                    required
                  />
                  <select
                    data-testid={`edit-symptom-severity-${symptom.id}`}
                    value={editSeverity}
                    onChange={(e) => setEditSeverity(e.target.value as 'mild' | 'moderate' | 'severe' | '')}
                    className="border p-1 rounded"
                  >
                    <option value="">None</option>
                    <option value="mild">Mild</option>
                    <option value="moderate">Moderate</option>
                    <option value="severe">Severe</option>
                  </select>
                  <button
                    data-testid={`btn-save-symptom-${symptom.id}`}
                    onClick={() => handleUpdate(symptom.id)}
                    className="text-green-600 underline text-sm"
                  >
                    Save
                  </button>
                  <button
                    data-testid={`btn-cancel-symptom-${symptom.id}`}
                    onClick={cancelEdit}
                    className="text-gray-500 underline text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 items-center flex-wrap">
                  <span className="font-medium">{symptom.name}</span>
                  {symptom.severity && (
                    <span className="text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded">
                      {symptom.severity}
                    </span>
                  )}
                  <ProvenanceBadge
                    sourceType={symptom.source_type}
                    verificationState={symptom.verification_state}
                  />
                  {symptom.source_type === 'SOURCE_DOCUMENT' && symptom.source_id && (
                    <button
                      data-testid={`link-document-${symptom.source_id}`}
                      className="text-sm text-blue-600 underline"
                      onClick={() => onViewDocument && onViewDocument(symptom.source_id!)}
                    >
                      View Source
                    </button>
                  )}
                </div>
              )}

              {editingId !== symptom.id && (
                <div className="flex gap-2">
                  <button
                    data-testid={`btn-edit-symptom-${symptom.id}`}
                    onClick={() => startEdit(symptom)}
                    className="text-blue-500 underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    data-testid={`btn-delete-symptom-${symptom.id}`}
                    onClick={() => handleDelete(symptom.id)}
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
