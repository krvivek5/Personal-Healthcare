import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { healthProfileApi, HealthProfileUpdate } from '../lib/api'

export const HealthProfileView: React.FC = () => {
  const { session } = useAuth()
  const token = session?.access_token
  
  const [loading, setLoading] = useState<boolean>(true)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  const [formData, setFormData] = useState<HealthProfileUpdate>({
    date_of_birth: '',
    biological_sex: '',
    blood_group: '',
    height_cm: null,
  })

  useEffect(() => {
    let isMounted = true
    const fetchProfile = async () => {
      if (!token) return
      
      try {
        setLoading(true)
        setError(null)
        const data = await healthProfileApi.get(token)
        if (isMounted) {
          setFormData({
            date_of_birth: data.date_of_birth || '',
            biological_sex: data.biological_sex || '',
            blood_group: data.blood_group || '',
            height_cm: data.height_cm || null,
          })
        }
      } catch (err: unknown) {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'Failed to load health profile')
        }
      } finally {
        if (isMounted) {
          setLoading(false)
        }
      }
    }

    fetchProfile()
    return () => {
      isMounted = false
    }
  }, [token])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'height_cm' ? (value ? parseFloat(value) : null) : value,
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!token) return
    
    try {
      setSaving(true)
      setError(null)
      await healthProfileApi.update(token, {
        date_of_birth: formData.date_of_birth || null,
        biological_sex: formData.biological_sex || null,
        blood_group: formData.blood_group || null,
        height_cm: formData.height_cm,
      })
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to update health profile')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div data-testid="health-profile-loading">Loading profile...</div>
  }

  return (
    <div className="health-profile-card" data-testid="health-profile-view">
      <h3>Basic Demographics</h3>
      
      {error && <div data-testid="health-profile-error" style={{ color: 'red', marginBottom: '1rem' }}>{error}</div>}
      
      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Date of Birth</label>
          <input
            data-testid="input-dob"
            type="date"
            name="date_of_birth"
            value={formData.date_of_birth || ''}
            onChange={handleChange}
            style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
          />
        </div>
        
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Biological Sex</label>
          <input
            data-testid="input-sex"
            type="text"
            name="biological_sex"
            value={formData.biological_sex || ''}
            onChange={handleChange}
            placeholder="e.g. Female"
            style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
          />
        </div>
        
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Blood Group</label>
          <input
            data-testid="input-blood"
            type="text"
            name="blood_group"
            value={formData.blood_group || ''}
            onChange={handleChange}
            placeholder="e.g. O+"
            style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
          />
        </div>
        
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Height (cm)</label>
          <input
            data-testid="input-height"
            type="number"
            step="0.1"
            name="height_cm"
            value={formData.height_cm === null ? '' : formData.height_cm}
            onChange={handleChange}
            placeholder="e.g. 170.5"
            style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
          />
        </div>

        <button 
          type="submit" 
          disabled={saving}
          data-testid="btn-save-profile"
          style={{ background: '#0f172a', color: 'white', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px', cursor: 'pointer' }}
        >
          {saving ? 'Saving...' : 'Save Profile'}
        </button>
      </form>
    </div>
  )
}
