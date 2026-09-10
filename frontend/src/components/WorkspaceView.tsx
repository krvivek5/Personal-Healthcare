import React, { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { HealthProfileView } from './HealthProfileView'
import { ConditionsList } from './ConditionsList'
import { SymptomsList } from './SymptomsList'
import { MedicationsList } from './MedicationsList'
import { AllergiesList } from './AllergiesList'
import { GoalsList } from './GoalsList'

export const WorkspaceView: React.FC = () => {
  const { user, isAnonymous, isLoading, convertToPermanent, signOut, clearAnonymousSession, error } = useAuth()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showConvertModal, setShowConvertModal] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [conversionSuccess, setConversionSuccess] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (isLoading) {
    return <div data-testid="auth-loading">Initializing secure workspace...</div>
  }

  const handleConvert = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsSubmitting(true)
    const ok = await convertToPermanent(email, password)
    setIsSubmitting(false)
    if (ok) {
      setConversionSuccess(true)
      setTimeout(() => {
        setShowConvertModal(false)
        setConversionSuccess(false)
      }, 1500)
    }
  }

  const handleClearSession = async () => {
    await clearAnonymousSession()
    setShowClearConfirm(false)
  }

  return (
    <div className="workspace-card" data-testid="workspace-view">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Personal Health Workspace</h2>
        <div>
          {isAnonymous ? (
            <span className="status-badge" style={{ backgroundColor: '#fef3c7', color: '#92400e', borderColor: '#fde68a' }} data-testid="identity-badge">
              Anonymous Workspace
            </span>
          ) : (
            <span className="status-badge" style={{ backgroundColor: '#ecfdf5', color: '#065f46', borderColor: '#a7f3d0' }} data-testid="identity-badge">
              Permanent Account
            </span>
          )}
        </div>
      </div>

      <p style={{ color: '#64748b', fontSize: '0.9rem' }}>
        Authenticated Identity ID: <code data-testid="user-id">{user?.id || 'none'}</code>
      </p>

      {isAnonymous ? (
        <div className="banner-anonymous" data-testid="anonymous-banner" style={{ background: '#fffbeb', padding: '1rem', borderRadius: '8px', border: '1px solid #fde68a', margin: '1rem 0' }}>
          <strong>Anonymous Session Active</strong>
          <p style={{ margin: '0.5rem 0', fontSize: '0.9rem' }}>
            You can immediately enter and record health observations without an upfront registration wall.
            To enable cross-device access and recovery, protect your workspace by converting to a permanent account.
          </p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
            <button
              data-testid="open-convert-btn"
              onClick={() => setShowConvertModal(true)}
              style={{ background: '#0284c7', color: 'white', border: 'none', padding: '0.5rem 1rem', borderRadius: '6px', cursor: 'pointer' }}
            >
              Protect Workspace (Link Email)
            </button>
            <button
              data-testid="open-clear-btn"
              onClick={() => setShowClearConfirm(true)}
              style={{ background: 'transparent', color: '#b91c1c', border: '1px solid #fca5a5', padding: '0.5rem 1rem', borderRadius: '6px', cursor: 'pointer' }}
            >
              Clear Workspace
            </button>
          </div>
        </div>
      ) : (
        <div style={{ margin: '1rem 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Account: <strong>{user?.email}</strong></span>
          <button
            data-testid="signout-btn"
            onClick={() => signOut()}
            style={{ background: '#64748b', color: 'white', border: 'none', padding: '0.4rem 0.8rem', borderRadius: '6px', cursor: 'pointer' }}
          >
            Sign Out
          </button>
        </div>
      )}

      <hr style={{ borderTop: '1px solid #e2e8f0', margin: '2rem 0' }} />
      <HealthProfileView />

      <hr style={{ borderTop: '1px solid #e2e8f0', margin: '2rem 0' }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        <ConditionsList />
        <SymptomsList />
        <MedicationsList />
        <AllergiesList />
        <GoalsList />
      </div>

      {/* Convert to Permanent Account Modal */}
      {showConvertModal && (
        <div className="modal-overlay" data-testid="convert-modal" style={{ background: 'rgba(0,0,0,0.5)', position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'white', padding: '1.5rem', borderRadius: '8px', maxWidth: '400px', width: '100%' }}>
            <h3>Protect Your Workspace</h3>
            <p style={{ fontSize: '0.85rem', color: '#64748b' }}>
              Linking an email and password converts this session into a permanent account while preserving all existing data and your unique identity.
            </p>
            {error && <div style={{ color: 'red', fontSize: '0.85rem', marginBottom: '0.5rem' }}>{error}</div>}
            {conversionSuccess ? (
              <div style={{ color: 'green', fontWeight: 'bold' }}>Account successfully converted!</div>
            ) : (
              <form onSubmit={handleConvert}>
                <div style={{ marginBottom: '0.75rem' }}>
                  <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Email</label>
                  <input
                    data-testid="convert-email-input"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
                  />
                </div>
                <div style={{ marginBottom: '1rem' }}>
                  <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Password</label>
                  <input
                    data-testid="convert-password-input"
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    style={{ width: '100%', padding: '0.5rem', boxSizing: 'border-box' }}
                  />
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                  <button type="button" onClick={() => setShowConvertModal(false)} style={{ padding: '0.5rem 1rem' }}>
                    Cancel
                  </button>
                  <button type="submit" data-testid="confirm-convert-btn" disabled={isSubmitting} style={{ background: '#0284c7', color: 'white', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}>
                    {isSubmitting ? 'Saving...' : 'Convert Account'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Clear Anonymous Session Confirmation Modal */}
      {showClearConfirm && (
        <div className="modal-overlay" data-testid="clear-confirm-modal" style={{ background: 'rgba(0,0,0,0.5)', position: 'fixed', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'white', padding: '1.5rem', borderRadius: '8px', maxWidth: '420px', width: '100%' }}>
            <h3 style={{ color: '#b91c1c' }}>Clear Anonymous Workspace?</h3>
            <p style={{ fontSize: '0.9rem', color: '#475569' }}>
              Warning: Any app-provided action that clears an anonymous session cannot be undone. This anonymous workspace cannot be recovered.
              If a new anonymous session is created, it will receive a new isolated identity.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
              <button data-testid="cancel-clear-btn" onClick={() => setShowClearConfirm(false)} style={{ padding: '0.5rem 1rem' }}>
                Cancel
              </button>
              <button
                data-testid="confirm-clear-btn"
                onClick={handleClearSession}
                style={{ background: '#b91c1c', color: 'white', border: 'none', padding: '0.5rem 1rem', borderRadius: '4px' }}
              >
                Permanently Clear
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
