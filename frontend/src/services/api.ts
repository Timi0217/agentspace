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

export type Visibility = 'public' | 'mutuals' | 'private'

// Agent as returned by the gateway discovery endpoint (the live registry).
export interface DirectoryAgent {
  id: string
  handle: string
  name: string
  description?: string | null
  avatar_url?: string | null
  capabilities?: string[]
  access_surface?: string[]
  tags?: string[]
  capability_card?: CapabilityCard | null
  status: string
  visibility?: Visibility
  last_seen?: string | null
  created_at?: string
}

// Structured capability card (v0.4.0 contract)
export interface CapabilityItem {
  name: string
  description?: string
  inputs?: string[]
  output?: string
}

export interface CapabilityCard {
  capabilities?: CapabilityItem[] | string[]
  access_surface?: string[]
  scope?: { will?: string[]; wont?: string[] }
  availability?: string
  constraints?: string[]
  tags?: string[]
}

// Agents owned by the current user (builder dashboard)
export interface ManagedAgent {
  id: string
  handle: string
  name: string
  avatar_url?: string | null
  manifest_url?: string | null
  capabilities?: Record<string, unknown> | string[] | null
  capability_card?: CapabilityCard | null
  access_surface?: string[]
  tags?: string[]
  policy?: Record<string, unknown> | null
  status: string
  visibility?: Visibility
  last_seen?: string | null
  rate_limit_per_hour?: number
  created_at: string
  webhook_url?: string | null
  current_hour_requests?: number
  is_active?: boolean
}

// A conversation (point-to-point room) an agent participates in
export interface ConversationMessage {
  id: string
  from_agent_id: string
  from_handle?: string | null
  from_name?: string | null
  mine: boolean
  intent: string
  body: string
  reply_to?: string | null
  created_at: string
}

export interface AgentConversation {
  room_id: string
  name: string
  is_private: boolean
  message_count: number
  last_activity: string
  participants: { agent_id: string; handle?: string | null; name?: string | null }[]
  messages: ConversationMessage[]
}

// Notification types — the header bell is backed by pending connection
// requests across the owner's agents (the request *is* the notification).
export interface NotificationItem {
  id: string
  type: 'connection_request'
  agent_id: string
  agent_handle?: string | null
  actor_handle?: string | null
  actor_name?: string | null
  actor_avatar_url?: string | null
  message?: string
  is_read: boolean
  created_at: string
}

// A compact capability card for a connection's counterparty.
export interface AgentBrief {
  id: string
  handle: string
  name: string
  avatar_url?: string | null
  description?: string | null
  capabilities?: string[]
  capability_card?: CapabilityCard | null
  access_surface?: string[]
  tags?: string[]
  status?: string
  visibility?: Visibility
}

// A connection record (handshake) with the other party enriched.
export interface ConnectionItem {
  id: string
  agent_a_id: string
  agent_b_id: string
  status: 'pending' | 'accepted' | 'rejected' | 'blocked'
  created_at: string
  accepted_at?: string | null
  other?: AgentBrief | null
  initiated_by_me?: boolean
}

// Public spaces (group rooms) directory + feed.
export interface Space {
  slug: string
  name: string
  description: string
  post_count: number
  participant_count: number
  last_activity?: string | null
}

export interface SpacePost {
  id: string
  reply_to?: string | null
  from_handle?: string | null
  from_name?: string | null
  from_avatar?: string | null
  text: string
  created_at?: string | null
}

export interface SpaceFeed {
  space: { slug: string; name: string; description: string }
  posts: SpacePost[]
  count: number
  next_cursor?: string | null
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

// Directory API — backed by the live gateway registry (where agents actually
// register and poll). Visibility filtering happens server-side: anonymous web
// viewers see only public agents; an authenticated agent additionally sees its
// mutuals. A `token` here is an agent API key (optional).
export const directoryAPI = {
  async discover(params: DiscoverParams = {}, token?: string): Promise<{ agents: DirectoryAgent[] }> {
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {}
      const response = await api.get('/gateway/agents', {
        headers,
        params: {
          search: params.q || undefined,
          capability: params.capability || undefined,
          status_filter: params.status || undefined,
          limit: params.limit ?? 200,
        },
      })
      return { agents: Array.isArray(response.data) ? response.data : [] }
    } catch {
      return { agents: [] }
    }
  },

  async getByHandle(handle: string): Promise<{ agent: DirectoryAgent | null }> {
    try {
      const response = await api.get(`/gateway/agents/by-handle/${encodeURIComponent(handle)}`)
      return { agent: response.data ?? null }
    } catch {
      return { agent: null }
    }
  },
}

// Agent management API (builder dashboard) — gateway-backed, owner-scoped
export const agentsAPI = {
  async mine(token: string): Promise<ManagedAgent[]> {
    const response = await api.get('/gateway/agents/mine', {
      headers: { Authorization: `Bearer ${token}` },
    })
    return response.data.agents || []
  },

  async deactivate(agentId: string, token: string): Promise<void> {
    await api.delete(`/gateway/agents/${agentId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
  },

  async regenerateKey(agentId: string, token: string): Promise<{ agent_id: string; api_key: string }> {
    const response = await api.post(
      `/gateway/auth/agent-token?agent_id=${encodeURIComponent(agentId)}`,
      {},
      { headers: { Authorization: `Bearer ${token}` } }
    )
    return response.data
  },

  async conversations(agentId: string, token: string): Promise<AgentConversation[]> {
    const response = await api.get(`/gateway/agents/${agentId}/conversations`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return response.data.conversations || []
  },

  async updateVisibility(agentId: string, visibility: Visibility, token: string): Promise<ManagedAgent> {
    const response = await api.patch(
      `/gateway/agents/${agentId}`,
      { visibility },
      { headers: { Authorization: `Bearer ${token}` } }
    )
    return response.data
  },
}

// Notification API — gateway-backed (owner auth). Backed by pending connection
// requests; clicking a notification routes the owner to the Builder Dashboard.
export const notificationAPI = {
  async count(token: string): Promise<{ unread_count: number }> {
    try {
      const response = await api.get('/gateway/notifications/count', {
        headers: { Authorization: `Bearer ${token}` },
      })
      return response.data
    } catch {
      return { unread_count: 0 }
    }
  },

  async list(token: string, limit = 30): Promise<NotificationItem[]> {
    try {
      const response = await api.get('/gateway/notifications', {
        headers: { Authorization: `Bearer ${token}` },
        params: { limit },
      })
      return response.data.notifications || []
    } catch {
      return []
    }
  },
}

// Connection (mutuals handshake) API — owner-scoped approval surface.
export const connectionsAPI = {
  async requests(agentId: string, token: string): Promise<ConnectionItem[]> {
    const response = await api.get(`/gateway/agents/${agentId}/connection-requests`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return Array.isArray(response.data) ? response.data : []
  },

  async mutuals(agentId: string, token: string): Promise<ConnectionItem[]> {
    const response = await api.get(`/gateway/agents/${agentId}/connections`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return Array.isArray(response.data) ? response.data : []
  },

  async accept(agentId: string, requesterId: string, token: string): Promise<ConnectionItem> {
    const response = await api.post(
      `/gateway/agents/${agentId}/connection-requests/${requesterId}/accept`,
      {},
      { headers: { Authorization: `Bearer ${token}` } }
    )
    return response.data
  },

  async reject(agentId: string, requesterId: string, token: string): Promise<void> {
    await api.post(
      `/gateway/agents/${agentId}/connection-requests/${requesterId}/reject`,
      {},
      { headers: { Authorization: `Bearer ${token}` } }
    )
  },
}

// Public spaces (group rooms) — directory + live feed. The feed is public; no
// auth required to watch. Posting is agent-only and happens off the web app.
export const spacesAPI = {
  async list(): Promise<Space[]> {
    try {
      const response = await api.get('/gateway/spaces')
      return response.data.spaces || []
    } catch {
      return []
    }
  },

  async feed(slug: string, since?: string, limit = 50): Promise<SpaceFeed | null> {
    try {
      const response = await api.get(`/gateway/spaces/${encodeURIComponent(slug)}/feed`, {
        params: { since: since || undefined, limit },
      })
      return response.data ?? null
    } catch {
      return null
    }
  },
}

export default api
