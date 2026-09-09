import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import React from 'react'
import { Session, User } from '@supabase/supabase-js'
import { AuthProvider, useAuth } from './AuthContext'
import { supabase } from '../lib/supabase'

vi.mock('../lib/supabase', () => ({
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

const createMockSession = (id: string, isAnonymous: boolean, email?: string): Session => {
  const user: User = {
    id,
    email,
    app_metadata: { provider: isAnonymous ? 'anonymous' : 'email' },
    user_metadata: {},
    aud: 'authenticated',
    created_at: '2026-09-08',
    is_anonymous: isAnonymous,
  }

  return {
    access_token: 'fake-jwt-token',
    token_type: 'bearer',
    expires_in: 3600,
    refresh_token: 'fake-refresh-token',
    user,
  }
}

describe('AuthContext Progressive Identity', () => {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <AuthProvider>{children}</AuthProvider>
  )

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('automatically establishes anonymous session when no existing session', async () => {
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: { session: null },
      error: null,
    })

    const anonSession = createMockSession('anon-user-1', true)
    vi.mocked(supabase.auth.signInAnonymously).mockResolvedValueOnce({
      data: {
        session: anonSession,
        user: anonSession.user,
      },
      error: null,
    })

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    expect(result.current.user?.id).toBe('anon-user-1')
    expect(result.current.isAnonymous).toBe(true)
    expect(supabase.auth.signInAnonymously).toHaveBeenCalledTimes(1)
  })

  it('converts anonymous identity to permanent while preserving user_id', async () => {
    const existingSession = createMockSession('user-keep-id', true)
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: {
        session: existingSession,
      },
      error: null,
    })

    const convertedUser: User = {
      id: 'user-keep-id', // Same user ID!
      email: 'permanent@example.com',
      app_metadata: { provider: 'email' },
      user_metadata: {},
      aud: 'authenticated',
      created_at: '2026-09-08',
      is_anonymous: false,
    }

    vi.mocked(supabase.auth.updateUser).mockResolvedValueOnce({
      data: {
        user: convertedUser,
      },
      error: null,
    })

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    let success = false
    await act(async () => {
      success = await result.current.convertToPermanent('permanent@example.com', 'SecurePass123!')
    })

    expect(success).toBe(true)
    expect(result.current.user?.id).toBe('user-keep-id')
    expect(result.current.user?.email).toBe('permanent@example.com')
    expect(result.current.isAnonymous).toBe(false)
  })

  it('clearing anonymous session requests explicit new anonymous identity', async () => {
    const oldSession = createMockSession('old-anon-id', true)
    vi.mocked(supabase.auth.getSession).mockResolvedValueOnce({
      data: {
        session: oldSession,
      },
      error: null,
    })

    const newSession = createMockSession('new-anon-id', true)
    vi.mocked(supabase.auth.signOut).mockResolvedValueOnce({ error: null })
    vi.mocked(supabase.auth.signInAnonymously).mockResolvedValueOnce({
      data: {
        session: newSession,
        user: newSession.user,
      },
      error: null,
    })

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false)
    })

    await act(async () => {
      await result.current.clearAnonymousSession()
    })

    expect(supabase.auth.signOut).toHaveBeenCalledTimes(1)
    expect(result.current.user?.id).toBe('new-anon-id')
  })
})
