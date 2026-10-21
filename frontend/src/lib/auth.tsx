import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, setUnauthorizedHandler } from './api'

export interface User {
  id: number
  email: string
  username: string
  full_name: string
  role: 'admin' | 'project_manager' | 'team_member'
  is_active: boolean
}

interface Session {
  user: User
  permissions: { finance: boolean; manage_projects: boolean; admin: boolean }
  integrations: { ai: boolean; email: boolean }
}

interface AuthCtx {
  session: Session | null
  loading: boolean
  login: (identifier: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  const refresh = useCallback(async () => {
    try {
      setSession(await api.get<Session>('/api/auth/me'))
    } catch {
      setSession(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    setUnauthorizedHandler(() => {
      setSession(null)
      qc.clear()
    })
  }, [refresh, qc])

  const login = async (identifier: string, password: string) => {
    await api.post('/api/auth/login', { identifier, password })
    await refresh()
  }

  const logout = async () => {
    try {
      await api.post('/api/auth/logout')
    } finally {
      qc.clear()
      setSession(null)
    }
  }

  return <Ctx.Provider value={{ session, loading, login, logout, refresh }}>{children}</Ctx.Provider>
}

export function useAuth() {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth outside provider')
  return c
}

/** Convenience accessor for components rendered inside protected routes. */
export function useSession() {
  const { session } = useAuth()
  if (!session) throw new Error('No session')
  return session
}
