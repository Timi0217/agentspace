import axios, { AxiosError } from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api/v1',
})

// Retry with exponential backoff for transient failures
const MAX_RETRIES = 3
const RETRYABLE_STATUS_CODES = new Set([408, 429, 500, 502, 503, 504])

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as any
    if (!config) return Promise.reject(error)

    config.__retryCount = config.__retryCount || 0

    const status = error.response?.status
    const isRetryable = !status || RETRYABLE_STATUS_CODES.has(status)
    const isIdempotent = config.method === 'get' || config.__retryCount === 0

    if (isRetryable && isIdempotent && config.__retryCount < MAX_RETRIES) {
      config.__retryCount += 1
      const delay = Math.min(1000 * Math.pow(2, config.__retryCount - 1), 8000)
      await new Promise((resolve) => setTimeout(resolve, delay))
      return api.request(config)
    }

    return Promise.reject(error)
  }
)

// Auth types and storage
export interface User {
  id: string
  login: string
  name?: string
  avatar_url?: string
}

export interface AuthToken {
  token: string
  user: User
  expires_at?: string
}

// Agent Registry API types
export interface RegistryAgent {
  id: string
  handle: string
  name: string
  description?: string
  avatar_url?: string
  status: string
  registered_at: string
  created_at: string
  last_seen?: string
  // Directory / discovery metadata
  builder_name?: string
  capabilities?: string[]
  pricing?: string
  price_per_call_usd?: string | number
  is_chekk_native?: boolean
  total_relay_calls: number
  last_probe_latency_ms?: number | null
  last_probe_at?: string | null
}

export interface DiscoverParams {
  q?: string
  status?: string
  capability?: string
  limit?: number
}

// Notification types
export interface NotificationItem {
  id: string
  actor_username: string
  actor_avatar_url?: string
  type: 'star' | 'comment' | 'remix' | 'follow'
  project_owner?: string
  project_repo?: string
  project_title?: string
  message?: string
  is_read: boolean
  created_at: string
}

// Auth functions
const AUTH_STORAGE_KEY = 'agentspace_auth'

export function getStoredAuth(): AuthToken | null {
  try {
    const stored = localStorage.getItem(AUTH_STORAGE_KEY)
    return stored ? JSON.parse(stored) : null
  } catch {
    return null
  }
}

export function setStoredAuth(auth: AuthToken): void {
  localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth))
}

// Convenience helper used after the GitHub OAuth redirect, where we have a
// raw token plus the user fields decoded from the URL hash.
export function storeAuth(token: string, user: Partial<User> & { login: string }): void {
  setStoredAuth({
    token,
    user: {
      id: user.id || user.login,
      login: user.login,
      name: user.name,
      avatar_url: user.avatar_url,
    },
  })
}

export function clearAuth(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY)
}

export function isAdmin(): boolean {
  const auth = getStoredAuth()
  return auth?.user?.login === 'admin' || false
}

export function loginWithGitHub(): void {
  // Kick off the OAuth flow on the backend. The backend holds the client secret,
  // exchanges the code, creates/loads the user account, and redirects back to
  // /auth/callback#auth=<session> which AgentsPage picks up on mount.
  const apiBase = import.meta.env.VITE_API_URL || '/api/v1'
  window.location.href = `${apiBase}/auth/login`
}

// Registry API
export const registryAPI = {
  async listAgents(token?: string): Promise<RegistryAgent[]> {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      const response = await api.get('/agents/registry', { headers })
      return response.data.agents || []
    } catch {
      return []
    }
  },

  async discover(params: DiscoverParams = {}, token?: string): Promise<{ agents: RegistryAgent[] }> {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      const response = await api.get('/agents/registry', { headers, params })
      return { agents: response.data.agents || [] }
    } catch {
      return { agents: [] }
    }
  },

  async getAgent(handle: string, token?: string): Promise<{ agent: RegistryAgent | null }> {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      const response = await api.get(`/agents/registry/${handle}`, { headers })
      return { agent: response.data.agent ?? response.data ?? null }
    } catch {
      return { agent: null }
    }
  },

  async registerAgent(data: { handle: string; name: string }, token: string): Promise<RegistryAgent> {
    const response = await api.post('/agents/registry', data, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return response.data
  },
}

// Notification API
export const notificationAPI = {
  async count(token: string): Promise<{ unread_count: number }> {
    try {
      const response = await api.get('/notifications/count', {
        headers: { Authorization: `Bearer ${token}` },
      })
      return response.data
    } catch {
      return { unread_count: 0 }
    }
  },

  async list(token: string, limit = 30): Promise<NotificationItem[]> {
    try {
      const response = await api.get('/notifications', {
        headers: { Authorization: `Bearer ${token}` },
        params: { limit },
      })
      return response.data.notifications || []
    } catch {
      return []
    }
  },

  async markRead(id: string, token: string): Promise<void> {
    await api.patch(
      `/notifications/${id}/read`,
      {},
      {
        headers: { Authorization: `Bearer ${token}` },
      }
    )
  },

  async markAllRead(token: string): Promise<void> {
    await api.patch(
      '/notifications/read-all',
      {},
      {
        headers: { Authorization: `Bearer ${token}` },
      }
    )
  },
}

export default api
