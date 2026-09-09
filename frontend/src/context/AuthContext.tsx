import React, { createContext, useContext, useEffect, useState } from 'react'
import { Session, User } from '@supabase/supabase-js'
import { supabase } from '../lib/supabase'

export interface AuthContextType {
  user: User | null
  session: Session | null
  isAnonymous: boolean
  isLoading: boolean
  error: string | null
  convertToPermanent: (email: string, password: string) => Promise<boolean>
  signOut: () => Promise<void>
  clearAnonymousSession: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [session, setSession] = useState<Session | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)

  const isAnonymous = Boolean(user?.is_anonymous || user?.app_metadata?.provider === 'anonymous')

  useEffect(() => {
    // 1. Check active session or initialize anonymous session
    const initAuth = async () => {
      try {
        setIsLoading(true)
        const { data: { session: existingSession } } = await supabase.auth.getSession()

        if (existingSession) {
          setSession(existingSession)
          setUser(existingSession.user)
        } else {
          // Anonymous-first: Establish an anonymous session immediately
          const { data, error: anonError } = await supabase.auth.signInAnonymously()
          if (anonError) {
            setError(anonError.message)
          } else if (data.session) {
            setSession(data.session)
            setUser(data.user)
          }
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to initialize session')
      } finally {
        setIsLoading(false)
      }
    }

    initAuth()

    // 2. Subscribe to auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, currentSession) => {
        setSession(currentSession)
        setUser(currentSession?.user ?? null)
        setIsLoading(false)
      }
    )

    return () => {
      subscription.unsubscribe()
    }
  }, [])

  // Progressive conversion: Attach permanent credentials to current anonymous user
  const convertToPermanent = async (email: string, password: string): Promise<boolean> => {
    try {
      setError(null)
      const { data, error: updateError } = await supabase.auth.updateUser({
        email,
        password,
      })

      if (updateError) {
        setError(updateError.message)
        return false
      }

      if (data.user) {
        setUser(data.user)
      }
      return true
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to convert account')
      return false
    }
  }

  // Permanent user sign out
  const signOut = async (): Promise<void> => {
    try {
      await supabase.auth.signOut()
      setUser(null)
      setSession(null)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to sign out')
    }
  }

  // Explicit anonymous session clearing
  const clearAnonymousSession = async (): Promise<void> => {
    try {
      setIsLoading(true)
      await supabase.auth.signOut()
      // Establish new isolated anonymous session
      const { data, error: anonError } = await supabase.auth.signInAnonymously()
      if (anonError) {
        setError(anonError.message)
      } else {
        setSession(data.session)
        setUser(data.user)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to reset anonymous workspace')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        session,
        isAnonymous,
        isLoading,
        error,
        convertToPermanent,
        signOut,
        clearAnonymousSession,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
