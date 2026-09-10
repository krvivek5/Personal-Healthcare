import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { Session, User } from '@supabase/supabase-js'
import App from './App'
import { supabase } from './lib/supabase'

vi.mock('./lib/supabase', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      signInAnonymously: vi.fn(),
      onAuthStateChange: vi.fn(() => ({
        data: { subscription: { unsubscribe: vi.fn() } },
      })),
      updateUser: vi.fn(),
      signOut: vi.fn(),
    },
  },
}))

const createMockSession = (id: string, isAnonymous: boolean): Session => {
  const user: User = {
    id,
    app_metadata: { provider: isAnonymous ? 'anonymous' : 'email' },
    user_metadata: {},
    aud: 'authenticated',
    created_at: '2026-09-08',
    is_anonymous: isAnonymous,
  }

  return {
    access_token: 'mock-access-token',
    token_type: 'bearer',
    expires_in: 3600,
    refresh_token: 'mock-refresh-token',
    user,
  }
}

describe('App Workspace & Progressive Identity Experience', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    global.fetch = vi.fn().mockImplementation(() =>
      Promise.resolve({
        json: () => Promise.resolve({ status: 'healthy' }),
      })
    )
  })

  it('allows user to immediately reach the personal health workspace with anonymous session', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: { session: createMockSession('anon-user-test-uuid', true) },
      error: null,
    })

    render(<App />)

    // User reaches workspace immediately without registration block
    expect(screen.getByText('Personal Healthcare Intelligence')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByTestId('workspace-view')).toBeInTheDocument()
      expect(screen.getByTestId('identity-badge')).toHaveTextContent('Anonymous Workspace')
      expect(screen.getByTestId('user-id')).toHaveTextContent('anon-user-test-uuid')
      expect(screen.getByTestId('anonymous-banner')).toBeInTheDocument()

      // Clinical lists are rendered
      expect(screen.getByText('Conditions')).toBeInTheDocument()
      expect(screen.getByText('Symptoms')).toBeInTheDocument()
      expect(screen.getByText('Medications')).toBeInTheDocument()
      expect(screen.getByText('Allergies')).toBeInTheDocument()
      expect(screen.getByText('Goals')).toBeInTheDocument()
    })
  })

  it('opens account conversion modal when user clicks Protect Workspace', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: { session: createMockSession('anon-user-test-uuid', true) },
      error: null,
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('open-convert-btn')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('open-convert-btn'))
    expect(screen.getByTestId('convert-modal')).toBeInTheDocument()
    expect(screen.getByTestId('convert-email-input')).toBeInTheDocument()
    expect(screen.getByTestId('convert-password-input')).toBeInTheDocument()
  })

  it('warns user before clearing anonymous session', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: { session: createMockSession('anon-user-test-uuid', true) },
      error: null,
    })

    render(<App />)

    await waitFor(() => {
      expect(screen.getByTestId('open-clear-btn')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByTestId('open-clear-btn'))
    expect(screen.getByTestId('clear-confirm-modal')).toBeInTheDocument()
    expect(
      screen.getByText(/This anonymous workspace cannot be recovered/i)
    ).toBeInTheDocument()
  })
})
