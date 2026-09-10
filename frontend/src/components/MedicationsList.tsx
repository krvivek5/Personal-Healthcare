import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { medicationsApi, Medication, MedicationCreate, MedicationUpdate } from '../lib/api'

export const MedicationsList: React.FC = () => {
  const { session } = useAuth()
  const [medications, setMedications] = useState<Medication[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [dosage, setDosage] = useState('')
  const [frequency, setFrequency] = useState('')
  const [status, setStatus] = useState<'active' | 'stopped'>('active')
  const [asNeeded, setAsNeeded] = useState(false)
  const [startedAt, setStartedAt] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDosage, setEditDosage] = useState('')
  const [editFrequency, setEditFrequency] = useState('')
  const [editStatus, setEditStatus] = useState<'active' | 'stopped'>('active')
  const [editAsNeeded, setEditAsNeeded] = useState(false)

  useEffect(() => {
    if (!session?.access_token) return
    let mounted = true

    const fetchMedications = async () => {
      try {
        const data = await medicationsApi.list(session.access_token)
        if (mounted) {
          setMedications(data)
          setIsLoading(false)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load medications')
          setIsLoading(false)
        }
      }
    }

    fetchMedications()
    return () => { mounted = false }
  }, [session?.access_token])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session?.access_token || !name.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const payload: MedicationCreate = {
        name: name.trim(),
        dosage: dosage.trim() || null,
        frequency: frequency.trim() || null,
        status,
        as_needed: asNeeded,
        ...(startedAt ? { started_at: startedAt } : {}),
      }
      const newMed = await medicationsApi.create(session.access_token, payload)
      setMedications([...medications, newMed])
      setName('')
      setDosage('')
      setFrequency('')
      setStatus('active')
      setAsNeeded(false)
      setStartedAt('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add medication')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!session?.access_token) return

    try {
      await medicationsApi.delete(session.access_token, id)
      setMedications(medications.filter(m => m.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete medication')
    }
  }

  const startEdit = (medication: Medication) => {
    setEditingId(medication.id)
    setEditName(medication.name)
    setEditDosage(medication.dosage || '')
    setEditFrequency(medication.frequency || '')
    setEditStatus(medication.status)
    setEditAsNeeded(medication.as_needed)
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token || !editName.trim()) return

    try {
      const payload: MedicationUpdate = {
        name: editName.trim(),
        dosage: editDosage.trim() || null,
        frequency: editFrequency.trim() || null,
        status: editStatus,
        as_needed: editAsNeeded,
      }
      const updatedMed = await medicationsApi.update(session.access_token, id, payload)
      setMedications(medications.map(m => m.id === id ? updatedMed : m))
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update medication')
    }
  }

  if (isLoading) return <div data-testid="medications-loading">Loading medications...</div>

  return (
    <div data-testid="medications-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Medications</h2>

      {error && <div data-testid="medications-error" className="text-red-500 mb-4">{error}</div>}

      <form onSubmit={handleAdd} className="mb-6 flex gap-2 items-end flex-wrap">
        <div>
          <label className="block text-sm">Medication Name</label>
          <input
            type="text"
            data-testid="input-med-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border p-2 rounded"
            required
          />
        </div>
        <div>
          <label className="block text-sm">Dosage</label>
          <input
            type="text"
            data-testid="input-med-dosage"
            value={dosage}
            onChange={(e) => setDosage(e.target.value)}
            className="border p-2 rounded w-24"
          />
        </div>
        <div>
          <label className="block text-sm">Frequency</label>
          <input
            type="text"
            data-testid="input-med-freq"
            value={frequency}
            onChange={(e) => setFrequency(e.target.value)}
            className="border p-2 rounded w-32"
          />
        </div>
        <div>
          <label className="block text-sm">Status</label>
          <select
            data-testid="input-med-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as 'active' | 'stopped')}
            className="border p-2 rounded"
          >
            <option value="active">Active</option>
            <option value="stopped">Stopped</option>
          </select>
        </div>
        <div>
          <label className="block text-sm">Started At</label>
          <input
            type="date"
            data-testid="input-med-started-at"
            value={startedAt}
            onChange={(e) => setStartedAt(e.target.value)}
            className="border p-2 rounded"
          />
        </div>
        <div>
          <label className="block text-sm flex items-center gap-1">
            <input
              type="checkbox"
              data-testid="input-med-prn"
              checked={asNeeded}
              onChange={(e) => setAsNeeded(e.target.checked)}
            />
            As needed (PRN)
          </label>
        </div>
        <button
          type="submit"
          data-testid="btn-add-med"
          disabled={isSubmitting}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          {isSubmitting ? 'Adding...' : 'Add'}
        </button>
      </form>

      {medications.length === 0 ? (
        <p>No medications recorded.</p>
      ) : (
        <ul className="space-y-2">
          {medications.map((medication) => (
            <li key={medication.id} className="border p-3 rounded flex justify-between items-center" data-testid={`med-item-${medication.id}`}>
              {editingId === medication.id ? (
                <div className="flex gap-2 items-center flex-wrap">
                  <input
                    type="text"
                    data-testid={`edit-med-name-${medication.id}`}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="border p-1 rounded"
                    required
                  />
                  <input
                    type="text"
                    data-testid={`edit-med-dosage-${medication.id}`}
                    value={editDosage}
                    onChange={(e) => setEditDosage(e.target.value)}
                    className="border p-1 rounded w-24"
                  />
                  <input
                    type="text"
                    data-testid={`edit-med-freq-${medication.id}`}
                    value={editFrequency}
                    onChange={(e) => setEditFrequency(e.target.value)}
                    className="border p-1 rounded w-24"
                  />
                  <select
                    data-testid={`edit-med-status-${medication.id}`}
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value as 'active' | 'stopped')}
                    className="border p-1 rounded"
                  >
                    <option value="active">Active</option>
                    <option value="stopped">Stopped</option>
                  </select>
                  <label className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      data-testid={`edit-med-prn-${medication.id}`}
                      checked={editAsNeeded}
                      onChange={(e) => setEditAsNeeded(e.target.checked)}
                    />
                    PRN
                  </label>
                  <button
                    data-testid={`btn-save-med-${medication.id}`}
                    onClick={() => handleUpdate(medication.id)}
                    className="text-green-600 underline text-sm"
                  >
                    Save
                  </button>
                  <button
                    data-testid={`btn-cancel-med-${medication.id}`}
                    onClick={cancelEdit}
                    className="text-gray-500 underline text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 items-center flex-wrap">
                  <span className="font-medium">{medication.name}</span>
                  {medication.dosage && (
                    <span className="text-sm text-gray-600">{medication.dosage}</span>
                  )}
                  {medication.frequency && (
                    <span className="text-sm text-gray-600">{medication.frequency}</span>
                  )}
                  <span className="text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded">
                    {medication.status}
                  </span>
                  {medication.as_needed && (
                    <span className="text-sm text-blue-600 bg-blue-100 px-2 py-1 rounded">
                      PRN
                    </span>
                  )}
                </div>
              )}

              {editingId !== medication.id && (
                <div className="flex gap-2">
                  <button
                    data-testid={`btn-edit-med-${medication.id}`}
                    onClick={() => startEdit(medication)}
                    className="text-blue-500 underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    data-testid={`btn-delete-med-${medication.id}`}
                    onClick={() => handleDelete(medication.id)}
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
