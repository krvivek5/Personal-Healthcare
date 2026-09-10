import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { conditionsApi, Condition, ConditionCreate, ConditionUpdate } from '../lib/api'

export const ConditionsList: React.FC = () => {
  const { session } = useAuth()
  const [conditions, setConditions] = useState<Condition[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [name, setName] = useState('')
  const [status, setStatus] = useState<'active' | 'resolved'>('active')
  const [isChronic, setIsChronic] = useState(false)
  const [startedAt, setStartedAt] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editStatus, setEditStatus] = useState<'active' | 'resolved'>('active')
  const [editIsChronic, setEditIsChronic] = useState(false)
  const [editStartedAt, setEditStartedAt] = useState('')

  useEffect(() => {
    if (!session?.access_token) return
    let mounted = true

    const fetchConditions = async () => {
      try {
        const data = await conditionsApi.list(session.access_token)
        if (mounted) {
          setConditions(data)
          setIsLoading(false)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load conditions')
          setIsLoading(false)
        }
      }
    }

    fetchConditions()
    return () => { mounted = false }
  }, [session?.access_token])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session?.access_token || !name.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const payload: ConditionCreate = {
        name: name.trim(),
        status,
        is_chronic: isChronic,
        ...(startedAt ? { started_at: startedAt } : {}),
      }
      const newCondition = await conditionsApi.create(session.access_token, payload)
      setConditions([...conditions, newCondition])
      setName('')
      setStatus('active')
      setIsChronic(false)
      setStartedAt('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add condition')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!session?.access_token) return

    try {
      await conditionsApi.delete(session.access_token, id)
      setConditions(conditions.filter(c => c.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete condition')
    }
  }

  const startEdit = (condition: Condition) => {
    setEditingId(condition.id)
    setEditStatus(condition.status)
    setEditIsChronic(condition.is_chronic)
    setEditStartedAt(condition.started_at || '')
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token) return

    try {
      const payload: ConditionUpdate = {
        status: editStatus,
        is_chronic: editIsChronic,
        ...(editStartedAt ? { started_at: editStartedAt } : {}),
      }
      const updatedCondition = await conditionsApi.update(session.access_token, id, payload)
      setConditions(conditions.map(c => c.id === id ? updatedCondition : c))
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update condition')
    }
  }

  if (isLoading) return <div data-testid="conditions-loading">Loading conditions...</div>

  return (
    <div data-testid="conditions-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Conditions</h2>

      {error && <div data-testid="conditions-error" className="text-red-500 mb-4">{error}</div>}

      <form onSubmit={handleAdd} className="mb-6 flex gap-2 items-end">
        <div>
          <label className="block text-sm">Condition Name</label>
          <input
            type="text"
            data-testid="input-condition-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="border p-2 rounded"
            required
          />
        </div>
        <div>
          <label className="block text-sm">Status</label>
          <select
            data-testid="input-condition-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as 'active' | 'resolved')}
            className="border p-2 rounded"
          >
            <option value="active">Active</option>
            <option value="resolved">Resolved</option>
          </select>
        </div>
        <div>
          <label className="block text-sm">Started At</label>
          <input
            type="date"
            data-testid="input-condition-started-at"
            value={startedAt}
            onChange={(e) => setStartedAt(e.target.value)}
            className="border p-2 rounded"
          />
        </div>
        <div>
          <label className="block text-sm flex items-center gap-1">
            <input
              type="checkbox"
              data-testid="input-condition-chronic"
              checked={isChronic}
              onChange={(e) => setIsChronic(e.target.checked)}
            />
            Chronic
          </label>
        </div>
        <button
          type="submit"
          data-testid="btn-add-condition"
          disabled={isSubmitting}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          {isSubmitting ? 'Adding...' : 'Add'}
        </button>
      </form>

      {conditions.length === 0 ? (
        <p>No conditions recorded.</p>
      ) : (
        <ul className="space-y-2">
          {conditions.map((condition) => (
            <li key={condition.id} className="border p-3 rounded flex justify-between items-center" data-testid={`condition-item-${condition.id}`}>
              {editingId === condition.id ? (
                <div className="flex gap-2 items-center">
                  <span className="font-medium">{condition.name}</span>
                  <select
                    data-testid={`edit-condition-status-${condition.id}`}
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value as 'active' | 'resolved')}
                    className="border p-1 rounded"
                  >
                    <option value="active">Active</option>
                    <option value="resolved">Resolved</option>
                  </select>
                  <input
                    type="date"
                    data-testid={`edit-condition-started-at-${condition.id}`}
                    value={editStartedAt}
                    onChange={(e) => setEditStartedAt(e.target.value)}
                    className="border p-1 rounded"
                  />
                  <label className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      data-testid={`edit-condition-chronic-${condition.id}`}
                      checked={editIsChronic}
                      onChange={(e) => setEditIsChronic(e.target.checked)}
                    />
                    Chronic
                  </label>
                  <button
                    data-testid={`btn-save-condition-${condition.id}`}
                    onClick={() => handleUpdate(condition.id)}
                    className="text-green-600 underline text-sm"
                  >
                    Save
                  </button>
                  <button
                    data-testid={`btn-cancel-condition-${condition.id}`}
                    onClick={cancelEdit}
                    className="text-gray-500 underline text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 items-center">
                  <span className="font-medium">{condition.name}</span>
                  <span className="text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded">
                    {condition.status}
                  </span>
                  {condition.is_chronic && (
                    <span className="text-sm text-yellow-600 bg-yellow-100 px-2 py-1 rounded">
                      Chronic
                    </span>
                  )}
                </div>
              )}

              {editingId !== condition.id && (
                <div className="flex gap-2">
                  <button
                    data-testid={`btn-edit-condition-${condition.id}`}
                    onClick={() => startEdit(condition)}
                    className="text-blue-500 underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    data-testid={`btn-delete-condition-${condition.id}`}
                    onClick={() => handleDelete(condition.id)}
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
