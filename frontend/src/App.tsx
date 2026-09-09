import { useState, useEffect } from 'react'
import './App.css'
import { AuthProvider } from './context/AuthContext'
import { WorkspaceView } from './components/WorkspaceView'

export function App() {
  const [apiStatus, setApiStatus] = useState<string>('checking...')

  useEffect(() => {
    fetch('/api/v1/health')
      .then((res) => res.json())
      .then((data) => setApiStatus(data.status || 'unknown'))
      .catch(() => setApiStatus('offline (start backend on :8000)'))
  }, [])

  return (
    <AuthProvider>
      <div className="app-container">
        <header className="header-card">
          <h1>Personal Healthcare Intelligence</h1>
          <p>Phase 1 — Personal Health Foundation</p>
          <div style={{ marginTop: '0.75rem', fontSize: '0.85rem' }}>
            Backend API status:{' '}
            <span className="status-badge" data-testid="api-status">
              {apiStatus}
            </span>
          </div>
        </header>

        <main>
          <WorkspaceView />
        </main>
      </div>
    </AuthProvider>
  )
}

export default App
