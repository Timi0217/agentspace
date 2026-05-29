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

export interface Deployment {
  id: string
  github_owner: string
  github_repo: string
  github_url: string
  status: 'pending' | 'cloning' | 'analyzing' | 'provisioning' | 'deploying' | 'live' | 'failed'
  framework: string | null
  deploy_target: string | null
  deployed_url: string | null
  error_message: string | null
  missing_env_vars: string[]
  detected_env_keys: (string | { key: string; hint: string | null; required: boolean; optional: boolean })[]
  root_directory: string | null
  build_log: string | null
  title: string | null
  description: string | null
  builder_github_username: string | null
  builder_display_name: string | null
  is_claimed: boolean
  claimed_at: string | null
  comment_count: number
  view_count: number
  like_count: number
  dislike_count: number
  star_count: number
  remix_count: number
  agent_call_count: number
  is_featured: string | null
  is_healthy: boolean
  health_check_count: number
  health_check_successes: number
  last_response_time_ms: number | null
  avg_response_time_ms: number | null
  stripe_payments_enabled: boolean
  agent_manifest: {
    schema: string
    name: string
    slug: string
    description: string
    entrypoints: string[]
    actions: { method: string; path: string; description: string }[]
    requirements?: Record<string, string>
  } | null
  created_at: string
  updated_at: string
}

export interface Comment {
  id: string
  deployment_id: string
  author_name: string
  body: string
  page_url: string | null
  github_username: string | null
  github_avatar_url: string | null
  github_display_name: string | null
  tag: string | null
  screenshot_url: string | null
  pin_x: number | null
  pin_y: number | null
  agent_message_id: string | null
  created_at: string
}

export interface Profile {
  id: string
  github_username: string
  display_name: string | null
  bio: string | null
  avatar_url: string | null
  website_url: string | null
  github_url: string | null
  twitter_handle: string | null
  follower_count: number
  following_count: number
  total_stars: number
  total_views: number
  featured: string | null
  pinned_project_ids: string[]
  currently_building: string | null
  base_payout_address: string | null
  created_at: string
}

export interface PaymentReceipt {
  id: string
  deployment_id: string
  owner: string
  repo: string
  method: string
  path: string
  amount_usd: string
  amount_usdc: string
  chain: string
  recipient_address: string
  status: string
  chekk_fee_usdc: string | null
  builder_net_usdc: string | null
  cdp_charge_id: string | null
  tx_hash: string | null
  payer_address: string | null
  created_at: string | null
  paid_at: string | null
  consumed_at: string | null
  expires_at: string | null
  payout_tx_hash: string | null
  payout_user_op_hash: string | null
  payout_at: string | null
  payout_error: string | null
}

export interface PayoutsResponse {
  username: string
  base_payout_address: string | null
  stats: {
    paid_receipts_count: number
    pending_receipts_count: number
    unique_agents_paid: number
    total_earned_usd: string
    paid_out_usd: string
    held_in_treasury_usd: string
  }
  receipts: PaymentReceipt[]
}

export interface ShippingDay {
  date: string
  count: number
  projects: string[]
}

export interface ShippingCalendar {
  username: string
  days: ShippingDay[]
  current_streak: number
  longest_streak: number
  total_deploys: number
  active_days: number
}

export interface RemixTreeNode {
  id: string
  github_owner: string
  github_repo: string
  title: string | null
  builder_github_username: string | null
  star_count: number
  children: RemixTreeNode[]
}

export interface RemixTree {
  root: RemixTreeNode
  total_remixes: number
}

export interface LiveDeployEvent {
  id: string
  github_owner: string
  github_repo: string
  framework: string | null
  builder_github_username: string | null
  builder_display_name: string | null
  is_claimed: boolean
  status: string
  title: string | null
  created_at: string
  deploy_time_seconds: number | null
}

export interface BuilderCard {
  github_username: string
  display_name: string | null
  avatar_url: string | null
  bio: string | null
  follower_count: number
  project_count: number
  total_stars: number
  is_following: boolean
}

export interface SidebarData {
  builder: BuilderCard
  is_claimed: boolean
  more_from_builder: Deployment[]
  related_projects: Deployment[]
  views_today: number
  views_this_week: number
  trending_in: string | null
}

export interface ProfileWithProjects extends Profile {
  projects: Deployment[]
  built_projects: Deployment[]
  pinned_projects: Deployment[]
  is_following: boolean
  shipping_streak: number
}

export interface RemixInfo {
  id: string
  github_owner: string
  github_repo: string
  title: string | null
}

export interface GitHubUser {
  login: string
  name: string | null
  avatar_url: string
  access_token: string
}

export interface RootCandidate {
  path: string
  framework: string | null
  recommended: boolean
  markers: string[]
  monorepo?: boolean
}

export const deployAPI = {
  scanRoot: (owner: string, repo: string, token?: string) =>
    api.get<{ candidates: RootCandidate[]; detected_env_keys: (string | { key: string; hint: string | null; required: boolean; optional: boolean })[] }>(`/deploy/scan-root/${owner}/${repo}`, token ? {
      headers: { Authorization: `Bearer ${token}` },
    } : undefined).then(r => r.data),

  start: (github_url: string, opts?: { title?: string; description?: string; token?: string; env_vars?: Record<string, string>; root_directory?: string }) => {
    const headers: Record<string, string> = {}
    if (opts?.token) headers['Authorization'] = `Bearer ${opts.token}`
    // Track anonymous deploys with session_id for post-login attribution
    if (!opts?.token) headers['X-Session-Id'] = getOrCreateSessionId()
    return api.post<Deployment>('/deploy', {
      github_url,
      ...(opts?.title && { title: opts.title }),
      ...(opts?.description && { description: opts.description }),
      ...(opts?.env_vars && Object.keys(opts.env_vars).length > 0 && { env_vars: opts.env_vars }),
      ...(opts?.root_directory && { root_directory: opts.root_directory }),
    }, { headers }).then(r => r.data)
  },

  get: (id: string) =>
    api.get<Deployment>(`/deploy/${id}`).then(r => r.data),

  getByUrl: (owner: string, repo: string) =>
    api.get<Deployment>(`/deploy/by-url/${owner}/${repo}`).then(r => r.data),

  submitEnvVars: (id: string, env_vars: Record<string, string>) =>
    api.post<Deployment>(`/deploy/${id}/env-vars`, { env_vars }).then(r => r.data),

  updateEnvVars: (id: string, env_vars: Record<string, string>) =>
    api.patch<Deployment>(`/deploy/${id}/env-vars`, { env_vars }).then(r => r.data),

  redeploy: (id: string, env_vars?: Record<string, string>) =>
    api.post<Deployment>(`/deploy/${id}/redeploy`, env_vars && Object.keys(env_vars).length > 0 ? { env_vars } : {}).then(r => r.data),

  cancel: (id: string) =>
    api.post<Deployment>(`/deploy/${id}/cancel`).then(r => r.data),

  recent: (limit = 20, sort: 'recent' | 'trending' | 'popular' | 'most_commented' | 'rising' | 'staff_picks' = 'recent', q?: string) =>
    api.get<Deployment[]>(`/deployments/recent`, { params: { limit, sort, ...(q ? { q } : {}) } }).then(r => r.data),

  vote: (id: string, direction: 'up' | 'down', token: string) =>
    api.post<{ like_count: number; dislike_count: number; user_vote: 'up' | 'down' | null }>(`/deploy/${id}/vote`, null, {
      params: { direction },
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  getVote: (id: string, token: string) =>
    api.get<{ user_vote: 'up' | 'down' | null }>(`/deploy/${id}/vote`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  update: (id: string, body: { title?: string; description?: string }, token: string) =>
    api.patch<Deployment>(`/deploy/${id}`, body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  delete: (id: string, token: string) =>
    api.delete(`/deploy/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  sidebar: (owner: string, repo: string, token?: string) =>
    api.get<SidebarData>(`/deploy/${owner}/${repo}/sidebar`, token ? {
      headers: { Authorization: `Bearer ${token}` },
    } : undefined).then(r => r.data),

  claim: (owner: string, repo: string, token: string) =>
    api.post<{ status: string; claimed_at: string }>(`/deploy/${owner}/${repo}/claim`, null, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  stripeToggle: (owner: string, repo: string, enabled: boolean, token: string) =>
    api.patch<{ stripe_payments_enabled: boolean }>(`/deploy/${owner}/${repo}/stripe`, { enabled }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),
}

export const commentAPI = {
  list: (deploymentId: string) =>
    api.get<Comment[]>(`/comments/${deploymentId}`).then(r => r.data),

  create: (deploymentId: string, body: string, token: string, opts?: {
    tag?: string; screenshot_url?: string; pin_x?: number; pin_y?: number; agent_message_id?: string
  }) =>
    api.post<Comment>(
      `/comments/${deploymentId}`,
      { body, ...opts },
      { headers: { Authorization: `Bearer ${token}` } }
    ).then(r => r.data),
}

export const profileAPI = {
  get: (username: string, token?: string) =>
    api.get<ProfileWithProjects>(`/profile/${username}`, token ? {
      headers: { Authorization: `Bearer ${token}` },
    } : undefined).then(r => r.data),

  update: (body: {
    display_name?: string; bio?: string; website_url?: string; twitter_handle?: string;
    pinned_project_ids?: string[]; currently_building?: string; base_payout_address?: string;
  }, token: string) =>
    api.patch<Profile>('/profile', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  shipping: (username: string, days = 365) =>
    api.get<ShippingCalendar>(`/profile/${username}/shipping`, { params: { days } }).then(r => r.data),

  githubContributions: (username: string) =>
    api.get<{ total: number; days: { date: string; level: number }[] }>(`/profile/${username}/github-contributions`).then(r => r.data),

  // Agent Highway: builder payout history + stats
  getPayouts: (token: string) =>
    api.get<PayoutsResponse>('/profile/me/payouts', {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),
}

export const followAPI = {
  toggle: (username: string, token: string) =>
    api.post<{ following: boolean; follower_count: number }>(`/follow/${username}`, null, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  followers: (username: string) =>
    api.get<{ followers: string[]; total: number }>(`/followers/${username}`).then(r => r.data),

  following: (username: string) =>
    api.get<{ following: string[]; total: number }>(`/following/${username}`).then(r => r.data),
}

export const starAPI = {
  toggle: (deploymentId: string, token: string) =>
    api.post<{ deployment_id: string; github_username: string; star_count: number; starred: boolean }>(
      `/deploy/${deploymentId}/star`, null,
      { headers: { Authorization: `Bearer ${token}` } }
    ).then(r => r.data),

  status: (deploymentId: string, token?: string) =>
    api.get<{ star_count: number; starred: boolean }>(
      `/deploy/${deploymentId}/star`,
      token ? { headers: { Authorization: `Bearer ${token}` } } : undefined
    ).then(r => r.data),

  userStars: (username: string) =>
    api.get<Deployment[]>(`/stars/${username}`).then(r => r.data),
}

export const remixAPI = {
  remix: (deploymentId: string, token: string) =>
    api.post<{ id: string; original_deployment_id: string; remix_deployment_id: string; remixer_username: string }>(
      '/remix', { deployment_id: deploymentId },
      { headers: { Authorization: `Bearer ${token}` } }
    ).then(r => r.data),

  remixes: (deploymentId: string) =>
    api.get<Deployment[]>(`/deploy/${deploymentId}/remixes`).then(r => r.data),

  remixedFrom: (deploymentId: string) =>
    api.get<{ remixed_from: RemixInfo | null }>(`/deploy/${deploymentId}/remixed-from`).then(r => r.data),

  tree: (deploymentId: string) =>
    api.get<RemixTree>(`/deploy/${deploymentId}/remix-tree`).then(r => r.data),
}

export const feedAPI = {
  following: (token: string, limit = 20) =>
    api.get<Deployment[]>('/feed/following', {
      params: { limit },
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  live: (limit = 20) =>
    api.get<LiveDeployEvent[]>('/feed/live', { params: { limit } }).then(r => r.data),
}

export const adminAPI = {
  feature: (deploymentId: string, featureType: 'weekly' | 'staff_pick', token: string) =>
    api.post<{ featured: boolean; type?: string }>(`/admin/feature/${deploymentId}`, null, {
      params: { feature_type: featureType },
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),
}

export interface FixResult {
  success: boolean
  pr_url: string | null
  pr_number: number | null
  branch_name: string | null
  files_changed: string[]
  diagnosis: string
  error: string | null
}

export const fixAPI = {
  fix: (deploymentId: string, token: string) =>
    api.post<FixResult>(`/deploy/${deploymentId}/fix`, null, {
      headers: { Authorization: `Bearer ${token}` },
      timeout: 120_000, // 2 min — AI analysis takes time
    }).then(r => r.data),
}

export const authAPI = {
  getLoginUrl: () => {
    const baseUrl = import.meta.env.VITE_API_URL || '/api/v1'
    return `${baseUrl}/auth/github`
  },

  exchangeCode: (code: string) =>
    api.post<GitHubUser>('/auth/github/callback', null, { params: { code } }).then(r => r.data),

  getMe: (token: string) =>
    api.get<{ login: string; name: string | null; avatar_url: string }>('/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  claimSession: (token: string, sessionId: string) =>
    api.post<{ claimed: number }>('/auth/claim-session', null, {
      headers: { Authorization: `Bearer ${token}`, 'X-Session-Id': sessionId },
    }).then(r => r.data),

  claimBatch: (token: string, deploymentIds: string[]) =>
    api.post<{ claimed: number }>('/deploy/claim-batch', { deployment_ids: deploymentIds }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),
}

// ── Anonymous session tracking ─────────────────────────────
const SESSION_ID_KEY = 'chekk_session_id'
const UNCLAIMED_DEPLOYS_KEY = 'chekk_unclaimed_deploys'

export function getOrCreateSessionId(): string {
  let sid = localStorage.getItem(SESSION_ID_KEY)
  if (!sid) {
    sid = crypto.randomUUID()
    localStorage.setItem(SESSION_ID_KEY, sid)
  }
  return sid
}

export function getSessionId(): string | null {
  return localStorage.getItem(SESSION_ID_KEY)
}

export function addUnclaimedDeploy(deploymentId: string) {
  const raw = localStorage.getItem(UNCLAIMED_DEPLOYS_KEY)
  const ids: string[] = raw ? JSON.parse(raw) : []
  if (!ids.includes(deploymentId)) {
    ids.push(deploymentId)
    localStorage.setItem(UNCLAIMED_DEPLOYS_KEY, JSON.stringify(ids))
  }
}

export function getUnclaimedDeploys(): string[] {
  const raw = localStorage.getItem(UNCLAIMED_DEPLOYS_KEY)
  return raw ? JSON.parse(raw) : []
}

export function clearUnclaimedDeploys() {
  localStorage.removeItem(UNCLAIMED_DEPLOYS_KEY)
}

// GitHub auth helpers using localStorage
const GH_TOKEN_KEY = 'chekk_gh_token'
const GH_USER_KEY = 'chekk_gh_user'

export function getStoredAuth(): { token: string; user: { login: string; name: string | null; avatar_url: string } } | null {
  const token = localStorage.getItem(GH_TOKEN_KEY)
  const userJson = localStorage.getItem(GH_USER_KEY)
  if (!token || !userJson) return null
  try {
    return { token, user: JSON.parse(userJson) }
  } catch {
    return null
  }
}

export function storeAuth(token: string, user: { login: string; name: string | null; avatar_url: string }) {
  localStorage.setItem(GH_TOKEN_KEY, token)
  localStorage.setItem(GH_USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(GH_TOKEN_KEY)
  localStorage.removeItem(GH_USER_KEY)
}

// Admin check — only the site owner can perform privileged actions
const ADMIN_USERNAMES = new Set(['Timi0217'])

export function isAdmin(): boolean {
  const auth = getStoredAuth()
  return !!auth && ADMIN_USERNAMES.has(auth.user.login)
}

export function loginWithGitHub() {
  localStorage.setItem('chekk_auth_redirect', window.location.pathname)
  // Pass the origin through the OAuth state parameter so the callback
  // can redirect back to the correct domain (e.g. agents4hire.dev)
  const loginUrl = authAPI.getLoginUrl()
  const sep = loginUrl.includes('?') ? '&' : '?'
  window.location.href = `${loginUrl}${sep}return_to=${encodeURIComponent(window.location.origin)}`
}

// Analytics types
export interface AnalyticsTimeBucket {
  time: string
  views: number
  unique: number
}

export interface AnalyticsData {
  deployment_id: string
  period: string
  total_views: number
  unique_visitors: number
  all_time_views: number
  star_count: number
  comment_count: number
  remix_count: number
  views_over_time: AnalyticsTimeBucket[]
  traffic_sources: { source: string; views: number }[]
  top_referrers: { url: string; views: number }[]
  countries: { country: string; views: number }[]
  stars_over_time: { time: string; count: number }[]
  comments_by_tag: { tag: string; count: number }[]
  peak_hours: { hour: number; views: number }[]
  peak_days: { day: number; views: number }[]
}

export const bookmarkAPI = {
  toggle: (deploymentId: string, token: string) =>
    api.post<{ deployment_id: string; github_username: string; bookmarked: boolean }>(
      `/deploy/${deploymentId}/bookmark`, null,
      { headers: { Authorization: `Bearer ${token}` } }
    ).then(r => r.data),

  status: (deploymentId: string, token?: string) =>
    api.get<{ bookmarked: boolean }>(
      `/deploy/${deploymentId}/bookmark`,
      token ? { headers: { Authorization: `Bearer ${token}` } } : undefined
    ).then(r => r.data),

  userBookmarks: (username: string) =>
    api.get<Deployment[]>(`/bookmarks/${username}`).then(r => r.data),
}

export const analyticsAPI = {
  get: (owner: string, repo: string, period: string = '7d') =>
    api.get<AnalyticsData>(`/analytics/${owner}/${repo}`, { params: { period } }).then(r => r.data),
}

export interface NotificationItem {
  id: string
  recipient_username: string
  actor_username: string
  type: 'star' | 'comment' | 'remix' | 'follow'
  deployment_id: string | null
  message: string | null
  is_read: boolean
  created_at: string
  actor_avatar_url: string | null
  project_title: string | null
  project_owner: string | null
  project_repo: string | null
}

// ── Growth Engine API ─────────────────────────────────────

export interface GrowthRepoItem {
  id: string
  github_owner: string
  github_repo: string
  github_url: string
  stars: number
  language: string | null
  description: string | null
  readme_preview: string | null
  has_frontend: boolean
  ai_tool_mention: string | null
  owner_email: string | null
  owner_name: string | null
  owner_avatar_url: string | null
  status: string
  deployment_id: string | null
  deployed_url: string | null
  deploy_error: string | null
  health_check_ok: boolean | null
  screenshot_url: string | null
  batch_id: string | null
  discovered_at: string | null
  deployed_at: string | null
  created_at: string | null
}

export interface DiscoveredRepo {
  owner: string
  repo: string
  full_name: string
  stars: number
  language: string | null
  description: string | null
  pushed_at: string | null
  url: string
  has_frontend: boolean
  ai_tool_mention: string | null
  owner_avatar: string | null
}

export interface OutreachRecord {
  id: string
  growth_repo_id: string | null
  recipient_email: string
  recipient_name: string | null
  subject: string
  body: string
  resend_email_id: string | null
  status: string
  opened_at: string | null
  clicked_at: string | null
  replied_at: string | null
  project_views_at_send: number
  sent_at: string | null
  created_at: string | null
}

export interface GrowthBuilderItem {
  id: string
  github_username: string
  display_name: string | null
  email: string | null
  avatar_url: string | null
  source: string
  growth_repo_id: string | null
  project_count: number
  last_active: string | null
  claimed: boolean
  created_at: string | null
}

export interface AgentMetrics {
  period_days: number
  total_calls: number
  unique_agents: number
  calls_by_tool: Record<string, number>
  top_projects: { owner: string; repo: string; calls: number }[]
  top_agents: { agent_id: string; calls: number }[]
  calls_per_day: { date: string; calls: number }[]
}

export interface GrowthMetrics {
  discovery: {
    total_discovered: number
    total_deployed: number
    total_failed: number
    deploy_success_rate: number
  }
  outreach: {
    total_sent: number
    total_emailed: number
    open_rate: number
    click_rate: number
    claim_rate: number
    total_claimed: number
  }
  builders: {
    total_builders: number
    active_this_week: number
    total_claimed: number
  }
  platform: {
    total_live_projects: number
  }
  framework_breakdown: Record<string, number>
}

export const growthAPI = {
  discover: (body: { languages: string[]; min_stars?: number; max_stars?: number; keywords?: string[]; max_results?: number; sort?: string; pushed_after?: string; has_frontend_only?: boolean; exclude_forks?: boolean; topic?: string }, token: string) =>
    api.post<{ repos: DiscoveredRepo[]; total: number }>('/growth/discover', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  addRepos: (repos: DiscoveredRepo[], token: string) =>
    api.post<{ added: number }>('/growth/repos', { repos: repos.map(r => ({ owner: r.owner, repo: r.repo, url: r.url, stars: r.stars, language: r.language, description: r.description, has_frontend: r.has_frontend, ai_tool_mention: r.ai_tool_mention, owner_avatar: r.owner_avatar })) }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  listRepos: (params?: { status?: string; batch_id?: string; limit?: number; offset?: number }) =>
    api.get<{ repos: GrowthRepoItem[]; total: number }>('/growth/repos', { params }).then(r => r.data),

  deployRepo: (repoId: string, token: string) =>
    api.post<{ status: string; deployment_id: string }>(`/growth/repos/${repoId}/deploy`, null, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  batchDeploy: (repoIds: string[], batchId: string, token: string) =>
    api.post<{ batch_id: string; results: { id: string; status: string }[] }>('/growth/repos/batch-deploy', { repo_ids: repoIds, batch_id: batchId }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  updateRepo: (repoId: string, body: Record<string, unknown>, token: string) =>
    api.patch(`/growth/repos/${repoId}`, body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  createOutreach: (body: { growth_repo_id?: string; recipient_email: string; recipient_name?: string; subject: string; body: string; send_now?: boolean }, token: string) =>
    api.post<{ id: string; status: string }>('/growth/outreach', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  listOutreach: (params?: { status?: string; limit?: number }) =>
    api.get<{ outreach: OutreachRecord[] }>('/growth/outreach', { params }).then(r => r.data),

  updateOutreach: (outreachId: string, body: { status: string }, token: string) =>
    api.patch(`/growth/outreach/${outreachId}`, body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  batchSendOutreach: (outreachIds: string[], token: string) =>
    api.post<{ results: { id: string; status: string }[] }>('/growth/outreach/batch-send', { outreach_ids: outreachIds }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  aiGenerateSingle: (growthRepoId: string, token: string) =>
    api.post<{ status: string; outreach_id: string; subject: string }>('/growth/outreach/ai-generate', { growth_repo_id: growthRepoId }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  batchGenerate: (growthRepoIds: string[], token: string, maxWorkers = 20) =>
    api.post<{ status: string; total: number; message: string }>('/growth/outreach/batch-generate', { growth_repo_ids: growthRepoIds, max_workers: maxWorkers }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  aiCompose: (data: { growth_repo_id?: string; owner_name?: string; github_owner?: string; github_repo?: string; description?: string; language?: string; deployed_url?: string }, token: string) =>
    api.post<{ subject: string; body: string; personalization_notes: string[]; success: boolean }>('/growth/outreach/ai-compose', data, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  getMetrics: () =>
    api.get<GrowthMetrics>('/growth/metrics').then(r => r.data),

  getAgentMetrics: (days = 30) =>
    api.get<AgentMetrics>('/agents/metrics', { params: { days } }).then(r => r.data),

  listBuilders: (params?: { source?: string; limit?: number }) =>
    api.get<{ builders: GrowthBuilderItem[] }>('/growth/builders', { params }).then(r => r.data),

  addBuilder: (body: { github_username: string; display_name?: string; email?: string; avatar_url?: string; source?: string; growth_repo_id?: string; project_count?: number; claimed?: boolean }, token: string) =>
    api.post<{ id: string; status: string }>('/growth/builders', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  // Hackathon pipeline
  hackathonIngest: (body: { prize_winners_only?: boolean; min_hackathon_id?: number; max_ingest?: number; check_github?: boolean }, token: string) =>
    api.post<{ status: string; message: string }>('/growth/hackathons/ingest', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  hackathonList: (params?: { status?: string; prize_only?: boolean; deployable_only?: boolean; limit?: number; offset?: number }) =>
    api.get<{ total: number; projects: HackathonProjectItem[] }>('/growth/hackathons', {
      params,
    }).then(r => r.data),

  hackathonStats: () =>
    api.get<HackathonStats>('/growth/hackathons/stats').then(r => r.data),

  hackathonPromote: (projectIds: string[], batchId: string, token: string) =>
    api.post<{ added: number; skipped: number }>('/growth/hackathons/promote', { project_ids: projectIds, batch_id: batchId }, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  hackathonBatchPromote: (body: { batch_id?: string; limit?: number }, token: string) =>
    api.post<{ added: number; skipped: number; total_eligible: number }>('/growth/hackathons/batch-promote', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  hackathonIngestStatus: () =>
    api.get<{ state: string; [key: string]: unknown }>('/growth/hackathons/ingest-status').then(r => r.data),

  hackathonClassifyTags: (token: string) =>
    api.post<{ classified: number; deployable: number; not_deployable: number }>('/growth/hackathons/classify-tags', {}, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  hackathonGithubCheck: (body: { tokens?: string[]; limit?: number }, token: string) =>
    api.post<{ status: string; message: string }>('/growth/hackathons/github-check', body, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  hackathonGithubCheckStatus: () =>
    api.get<{ state: string; checked: number; total: number; deployable: number; errors: number; error?: string }>('/growth/hackathons/github-check-status').then(r => r.data),
}

export interface HackathonProjectItem {
  id: string
  title: string
  brief_desc: string | null
  devpost_url: string | null
  hackathon_name: string | null
  hackathon_id: number | null
  prize: string | null
  tags: string | null
  team_members: string | null
  github_url: string | null
  github_owner: string | null
  github_repo: string | null
  stars: number
  language: string | null
  has_deploy_config: boolean
  has_frontend: boolean
  status: string
  deployed_url: string | null
  growth_repo_id: string | null
  ingested_at: string | null
}

export interface HackathonStats {
  total_ingested: number
  with_github_repo: number
  deployable: number
  deployed: number
  prize_winners: number
  in_growth_pipeline: number
}

// ── Chekk Finance Agent ──────────────────────────────────────────────
export interface ChekkResultMeta {
  freshness: string
  source: string
  cache_age_seconds: number
  fallback_used: boolean
  latency_ms: number
}

export interface ChekkResult {
  // Wrapped form (if normalizer wraps)
  data?: Record<string, any>
  meta?: ChekkResultMeta
  // Flat form (current behavior — raw normalized data)
  [key: string]: any
}

export interface ChekkResponse {
  schema_version: string
  status: 'success' | 'partial' | 'error'
  type: 'data' | 'action' | 'analysis'
  results: ChekkResult[]
  errors: { code: string; detail: string; retryable: boolean }[]
}

export const chekkAPI = {
  query: (request: string) =>
    api.post<ChekkResponse>('/chekk', { request }).then(r => r.data),
}

// ── Agent Registry (Agents4Hire Directory) ────────────────────────

export interface RegistryBuilder {
  id: string
  email: string
  name: string
  github_username: string | null
  bio: string | null
  website_url: string | null
  is_active: boolean
  created_at: string
}

export interface RegistryAgent {
  id: string
  handle: string
  name: string
  builder_id: string
  builder_name: string | null
  callback_url: string
  description: string | null
  capabilities: string[]
  pricing: string | null
  price_per_call_usd: string | null
  status: 'online' | 'offline' | 'probation'
  last_probe_at: string | null
  last_probe_latency_ms: number | null
  total_relay_calls: number
  is_public: boolean
  is_chekk_native: boolean
  created_at: string
}

const A4H_KEY = 'a4h_api_key'
const A4H_BUILDER_KEY = 'a4h_builder'

export function storeA4HAuth(apiKey: string, builder: RegistryBuilder) {
  localStorage.setItem(A4H_KEY, apiKey)
  localStorage.setItem(A4H_BUILDER_KEY, JSON.stringify(builder))
}

export function getA4HAuth(): { apiKey: string; builder: RegistryBuilder } | null {
  const key = localStorage.getItem(A4H_KEY)
  const raw = localStorage.getItem(A4H_BUILDER_KEY)
  if (!key || !raw) return null
  try {
    return { apiKey: key, builder: JSON.parse(raw) }
  } catch {
    return null
  }
}

export function clearA4HAuth() {
  localStorage.removeItem(A4H_KEY)
  localStorage.removeItem(A4H_BUILDER_KEY)
}

export const registryAPI = {
  // ── Builder ──
  signup: (body: { email: string; name: string; password: string; github_username?: string; bio?: string; website_url?: string }) =>
    api.post<{ builder: RegistryBuilder; api_key: string; message: string }>('/registry/builders/signup', body).then(r => r.data),

  signupGitHub: (ghToken: string) =>
    api.post<{ builder: RegistryBuilder; api_key: string }>('/registry/builders/signup-github', null, {
      headers: { Authorization: `Bearer ${ghToken}` },
    }).then(r => r.data),

  login: (body: { email: string; password: string }) =>
    api.post<{ builder: RegistryBuilder }>('/registry/builders/login', body).then(r => r.data),

  me: (apiKey: string) =>
    api.get<{ builder: RegistryBuilder }>('/registry/builders/me', {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  myAgents: (apiKey: string) =>
    api.get<{ agents: RegistryAgent[] }>('/registry/builders/me/agents', {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  // ── Agents (public) ──
  discover: (params?: { capability?: string; q?: string; status?: string; limit?: number; offset?: number }) =>
    api.get<{ agents: RegistryAgent[]; count: number }>('/registry/agents', { params }).then(r => r.data),

  getAgent: (handle: string) =>
    api.get<{ agent: RegistryAgent }>(`/registry/agents/${handle}`).then(r => r.data),

  // ── Agents (authenticated) ──
  register: (body: { handle: string; name: string; callback_url: string; pricing?: string; price_per_call_usd?: string; is_public?: boolean }, apiKey: string) =>
    api.post<{ agent: RegistryAgent; message: string }>('/registry/agents', body, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  update: (agentId: string, body: { name?: string; callback_url?: string; pricing?: string; price_per_call_usd?: string; is_public?: boolean }, apiKey: string) =>
    api.patch<{ agent: RegistryAgent }>(`/registry/agents/${agentId}`, body, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  deleteAgent: (agentId: string, apiKey: string) =>
    api.delete(`/registry/agents/${agentId}`, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  // ── Relay ──
  relay: (body: { from_handle: string; to_handle: string; message: Record<string, unknown> }, apiKey: string) =>
    api.post('/registry/relay', body, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),

  // ── Probe ──
  probe: (handle: string, apiKey: string) =>
    api.post(`/registry/agents/${handle}/probe`, null, {
      headers: { Authorization: `Bearer ${apiKey}` },
    }).then(r => r.data),
}

export const notificationAPI = {
  list: (token: string, limit = 50) =>
    api.get<NotificationItem[]>('/notifications', {
      params: { limit },
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  count: (token: string) =>
    api.get<{ unread_count: number }>('/notifications/count', {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  markAllRead: (token: string) =>
    api.post('/notifications/read-all', null, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),

  markRead: (notificationId: string, token: string) =>
    api.post(`/notifications/${notificationId}/read`, null, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.data),
}
