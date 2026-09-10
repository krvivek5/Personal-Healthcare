import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { goalsApi, Goal, GoalCreate, GoalUpdate } from '../lib/api'

export const GoalsList: React.FC = () => {
  const { session } = useAuth()
  const [goals, setGoals] = useState<Goal[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Form state
  const [description, setDescription] = useState('')
  const [status, setStatus] = useState<'active' | 'achieved' | 'abandoned'>('active')
  const [targetDate, setTargetDate] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDescription, setEditDescription] = useState('')
  const [editStatus, setEditStatus] = useState<'active' | 'achieved' | 'abandoned'>('active')
  const [editTargetDate, setEditTargetDate] = useState('')

  useEffect(() => {
    if (!session?.access_token) return
    let mounted = true

    const fetchGoals = async () => {
      try {
        const data = await goalsApi.list(session.access_token)
        if (mounted) {
          setGoals(data)
          setIsLoading(false)
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load goals')
          setIsLoading(false)
        }
      }
    }

    fetchGoals()
    return () => { mounted = false }
  }, [session?.access_token])

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!session?.access_token || !description.trim()) return

    setIsSubmitting(true)
    setError(null)

    try {
      const payload: GoalCreate = {
        description: description.trim(),
        status,
        target_date: targetDate || null,
      }
      const newGoal = await goalsApi.create(session.access_token, payload)
      setGoals([...goals, newGoal])
      setDescription('')
      setStatus('active')
      setTargetDate('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add goal')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!session?.access_token) return

    try {
      await goalsApi.delete(session.access_token, id)
      setGoals(goals.filter(g => g.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete goal')
    }
  }

  const startEdit = (goal: Goal) => {
    setEditingId(goal.id)
    setEditDescription(goal.description)
    setEditStatus(goal.status)
    setEditTargetDate(goal.target_date || '')
  }

  const cancelEdit = () => {
    setEditingId(null)
  }

  const handleUpdate = async (id: string) => {
    if (!session?.access_token || !editDescription.trim()) return

    try {
      const payload: GoalUpdate = {
        description: editDescription.trim(),
        status: editStatus,
        target_date: editTargetDate || null,
      }
      const updatedGoal = await goalsApi.update(session.access_token, id, payload)
      setGoals(goals.map(g => g.id === id ? updatedGoal : g))
      setEditingId(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update goal')
    }
  }

  if (isLoading) return <div data-testid="goals-loading">Loading goals...</div>

  return (
    <div data-testid="goals-list" className="p-4 border rounded shadow-sm bg-white mb-4">
      <h2 className="text-xl font-semibold mb-4">Goals</h2>

      {error && <div data-testid="goals-error" className="text-red-500 mb-4">{error}</div>}

      <form onSubmit={handleAdd} className="mb-6 flex gap-2 items-end flex-wrap">
        <div className="flex-grow">
          <label className="block text-sm">Description</label>
          <input
            type="text"
            data-testid="input-goal-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="border p-2 rounded w-full"
            required
          />
        </div>
        <div>
          <label className="block text-sm">Target Date</label>
          <input
            type="date"
            data-testid="input-goal-target-date"
            value={targetDate}
            onChange={(e) => setTargetDate(e.target.value)}
            className="border p-2 rounded"
          />
        </div>
        <div>
          <label className="block text-sm">Status</label>
          <select
            data-testid="input-goal-status"
            value={status}
            onChange={(e) => setStatus(e.target.value as 'active' | 'achieved' | 'abandoned')}
            className="border p-2 rounded"
          >
            <option value="active">Active</option>
            <option value="achieved">Achieved</option>
            <option value="abandoned">Abandoned</option>
          </select>
        </div>
        <button
          type="submit"
          data-testid="btn-add-goal"
          disabled={isSubmitting}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          {isSubmitting ? 'Adding...' : 'Add'}
        </button>
      </form>

      {goals.length === 0 ? (
        <p>No goals recorded.</p>
      ) : (
        <ul className="space-y-2">
          {goals.map((goal) => (
            <li key={goal.id} className="border p-3 rounded flex justify-between items-center" data-testid={`goal-item-${goal.id}`}>
              {editingId === goal.id ? (
                <div className="flex gap-2 items-center flex-wrap w-full">
                  <input
                    type="text"
                    data-testid={`edit-goal-description-${goal.id}`}
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    className="border p-1 rounded flex-grow"
                    required
                  />
                  <input
                    type="date"
                    data-testid={`edit-goal-target-date-${goal.id}`}
                    value={editTargetDate}
                    onChange={(e) => setEditTargetDate(e.target.value)}
                    className="border p-1 rounded"
                  />
                  <select
                    data-testid={`edit-goal-status-${goal.id}`}
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value as 'active' | 'achieved' | 'abandoned')}
                    className="border p-1 rounded"
                  >
                    <option value="active">Active</option>
                    <option value="achieved">Achieved</option>
                    <option value="abandoned">Abandoned</option>
                  </select>
                  <button
                    data-testid={`btn-save-goal-${goal.id}`}
                    onClick={() => handleUpdate(goal.id)}
                    className="text-green-600 underline text-sm"
                  >
                    Save
                  </button>
                  <button
                    data-testid={`btn-cancel-goal-${goal.id}`}
                    onClick={cancelEdit}
                    className="text-gray-500 underline text-sm"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 items-center flex-wrap">
                  <span className="font-medium">{goal.description}</span>
                  {goal.target_date && (
                    <span className="text-sm text-gray-600">By: {goal.target_date}</span>
                  )}
                  <span className="text-sm text-gray-600 bg-gray-100 px-2 py-1 rounded">
                    {goal.status}
                  </span>
                </div>
              )}

              {editingId !== goal.id && (
                <div className="flex gap-2">
                  <button
                    data-testid={`btn-edit-goal-${goal.id}`}
                    onClick={() => startEdit(goal)}
                    className="text-blue-500 underline text-sm"
                  >
                    Edit
                  </button>
                  <button
                    data-testid={`btn-delete-goal-${goal.id}`}
                    onClick={() => handleDelete(goal.id)}
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
