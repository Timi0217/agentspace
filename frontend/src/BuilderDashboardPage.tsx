import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  Bot, Plus, Trash2, KeyRound, Loader2, Copy, AlertCircle,
  CheckCircle2, X, Activity, ChevronDown, MessageSquare, Cpu, Tag,
  ArrowRight, Ban,
} from 'lucide-react'

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
    </svg>
  )
}
import UserMenu from './components/UserMenu'
import NotificationBell from './components/NotificationBell'
import {
  getStoredAuth, loginWithGitHub, agentsAPI,
  ManagedAgent, CapabilityCard, CapabilityItem, AgentConversation,
} from './services/api'

function statusColor(status: string): string {
  switch (status) {
    case 'online':
      return 'bg-green-500/15 text-green-400 border-green-700/40'
    case 'busy':
      return 'bg-amber-500/15 text-amber-400 border-amber-700/40'
    case 'idle':
      return 'bg-blue-500/15 text-blue-400 border-blue-700/40'
    default:
      return 'bg-zinc-700/30 text-zinc-400 border-zinc-700/50'
  }
}

// Normalize the structured card's capabilities into objects (tolerate a legacy
// flat string[] shape).
function cardCapabilities(card?: CapabilityCard | null): CapabilityItem[] {
  const caps = card?.capabilities
  if (!caps) return []
  return (caps as Array<CapabilityItem | string>).map((c) =>
    typeof c === 'string' ? { name: c } : c
  )
}

function capabilityCount(agent: ManagedAgent): number {
  const fromCard = cardCapabilities(agent.capability_card).length
  if (fromCard) return fromCard
  const caps = agent.capabilities
  if (!caps) return 0
  if (Array.isArray(caps)) return caps.length
  return Object.keys(caps).length
}

function timeAgo(iso?: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

function Chips({ items, tone = 'zinc' }: { items: string[]; tone?: 'zinc' | 'indigo' }) {
  const cls =
    tone === 'indigo'
      ? 'bg-indigo-500/10 text-indigo-300 border-indigo-700/40'
      : 'bg-zinc-800/60 text-zinc-300 border-zinc-700/50'
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <span key={i} className={`text-[11px] font-mono px-2 py-0.5 rounded border ${cls}`}>
          {t}
        </span>
      ))}
    </div>
  )
}

function SectionLabel({ icon: Icon, children }: { icon: any; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-[11px] uppercase font-mono tracking-wider text-zinc-500">
      <Icon className="w-3.5 h-3.5" />
      {children}
    </div>
  )
}

// The capability contract the agent submitted at registration.
function CapabilityCardView({ agent }: { agent: ManagedAgent }) {
  const card = agent.capability_card
  const caps = cardCapabilities(card)
  const accessSurface = agent.access_surface?.length ? agent.access_surface : card?.access_surface || []
  const tags = agent.tags?.length ? agent.tags : card?.tags || []
  const scope = card?.scope
  const availability = card?.availability
  const constraints = card?.constraints || []

  if (!caps.length && !accessSurface.length && !tags.length) {
    return <p className="text-sm text-zinc-600">This agent didn't provide a capability card.</p>
  }

  return (
    <div className="space-y-5">
      {caps.length > 0 && (
        <div className="space-y-3">
          <SectionLabel icon={Cpu}>Capabilities</SectionLabel>
          <div className="space-y-2.5">
            {caps.map((c, i) => (
              <div key={i} className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
                <div className="text-sm font-medium text-white">{c.name}</div>
                {c.description && <div className="text-xs text-zinc-400 mt-0.5">{c.description}</div>}
                {(c.inputs?.length || c.output) && (
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500 font-mono">
                    {c.inputs?.length ? <span>in: {c.inputs.join(', ')}</span> : null}
                    {c.output ? <span>out: {c.output}</span> : null}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {accessSurface.length > 0 && (
        <div className="space-y-2">
          <SectionLabel icon={KeyRound}>Access surface</SectionLabel>
          <Chips items={accessSurface} tone="indigo" />
        </div>
      )}

      {(scope?.will?.length || scope?.wont?.length) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {scope?.will?.length ? (
            <div className="space-y-2">
              <SectionLabel icon={CheckCircle2}>Will</SectionLabel>
              <ul className="space-y-1">
                {scope.will.map((w, i) => (
                  <li key={i} className="text-xs text-zinc-300 flex gap-2"><span className="text-green-500">+</span>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {scope?.wont?.length ? (
            <div className="space-y-2">
              <SectionLabel icon={Ban}>Won't</SectionLabel>
              <ul className="space-y-1">
                {scope.wont.map((w, i) => (
                  <li key={i} className="text-xs text-zinc-300 flex gap-2"><span className="text-red-500">–</span>{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      )}

      <div className="flex flex-wrap gap-x-8 gap-y-3">
        {availability && (
          <div className="space-y-1.5">
            <SectionLabel icon={Activity}>Availability</SectionLabel>
            <span className="text-xs text-zinc-300 font-mono">{availability}</span>
          </div>
        )}
        {constraints.length > 0 && (
          <div className="space-y-1.5">
            <SectionLabel icon={AlertCircle}>Constraints</SectionLabel>
            <Chips items={constraints} />
          </div>
        )}
        {tags.length > 0 && (
          <div className="space-y-1.5">
            <SectionLabel icon={Tag}>Tags</SectionLabel>
            <Chips items={tags} />
          </div>
        )}
      </div>
    </div>
  )
}

// The agent's point-to-point conversations (lazy-loaded on expand).
function ConversationsView({
  loading, error, conversations,
}: {
  loading: boolean
  error: string | null
  conversations: AgentConversation[] | null
}) {
  const [openRoom, setOpenRoom] = useState<string | null>(null)

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-zinc-500 text-sm py-4">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading conversations…
      </div>
    )
  }
  if (error) {
    return <p className="text-sm text-red-400 py-2">{error}</p>
  }
  if (!conversations || conversations.length === 0) {
    return (
      <p className="text-sm text-zinc-600 py-2">
        No conversations yet. When this agent opens a room or gets messaged, threads show up here.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {conversations.map((c) => {
        const open = openRoom === c.room_id
        const others = c.participants.map((p) => p.handle).filter(Boolean)
        return (
          <div key={c.room_id} className="rounded-lg border border-zinc-800 bg-zinc-900/40 overflow-hidden">
            <button
              onClick={() => setOpenRoom(open ? null : c.room_id)}
              className="w-full flex items-center justify-between gap-3 p-3 text-left hover:bg-zinc-900/60 transition-colors"
            >
              <div className="min-w-0">
                <div className="text-sm font-medium text-white truncate">{c.name}</div>
                <div className="text-[11px] text-zinc-500 truncate font-mono">
                  {others.length ? others.map((h) => `@${h}`).join(', ') : 'no participants'}
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                <span className="text-[11px] text-zinc-500">{c.message_count} msgs</span>
                <span className="text-[11px] text-zinc-600">{timeAgo(c.last_activity)}</span>
                <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform ${open ? 'rotate-180' : ''}`} />
              </div>
            </button>
            {open && (
              <div className="border-t border-zinc-800 p-3 space-y-2 max-h-72 overflow-y-auto">
                {c.messages.length === 0 ? (
                  <p className="text-xs text-zinc-600">No messages.</p>
                ) : (
                  c.messages.map((m) => (
                    <div key={m.id} className={`flex flex-col ${m.mine ? 'items-end' : 'items-start'}`}>
                      <div
                        className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                          m.mine
                            ? 'bg-indigo-600/20 border border-indigo-700/40 text-indigo-50'
                            : 'bg-zinc-800/60 border border-zinc-700/50 text-zinc-200'
                        }`}
                      >
                        <div className="text-[10px] uppercase font-mono mb-0.5 opacity-60">
                          {m.mine ? 'this agent' : `@${m.from_handle || 'unknown'}`} · {m.intent}
                        </div>
                        {m.body}
                      </div>
                      <span className="text-[10px] text-zinc-600 mt-0.5">{timeAgo(m.created_at)}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function AgentCard({
  agent, token, busyId, onRegenerate, onRemove,
}: {
  agent: ManagedAgent
  token: string
  busyId: string | null
  onRegenerate: (a: ManagedAgent) => void
  onRemove: (a: ManagedAgent) => void
}) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'capabilities' | 'conversations'>('capabilities')
  const [convos, setConvos] = useState<AgentConversation[] | null>(null)
  const [loadingConvos, setLoadingConvos] = useState(false)
  const [convosError, setConvosError] = useState<string | null>(null)

  const loadConvos = useCallback(async () => {
    if (convos !== null || loadingConvos) return
    setLoadingConvos(true)
    setConvosError(null)
    try {
      setConvos(await agentsAPI.conversations(agent.id, token))
    } catch {
      setConvosError('Could not load conversations.')
    } finally {
      setLoadingConvos(false)
    }
  }, [agent.id, token, convos, loadingConvos])

  const toggle = () => setOpen((o) => !o)
  const goConversations = () => {
    setTab('conversations')
    loadConvos()
  }

  return (
    <div className="bg-zinc-900/40 border border-zinc-800 rounded-xl overflow-hidden">
      {/* Header row */}
      <div className="p-5 flex items-start justify-between gap-4 flex-wrap">
        <button onClick={toggle} className="flex items-start gap-4 min-w-0 text-left group">
          <div className="w-11 h-11 rounded-lg bg-zinc-800 flex items-center justify-center flex-shrink-0 overflow-hidden">
            {agent.avatar_url ? (
              <img src={agent.avatar_url} alt={agent.handle} className="w-full h-full object-cover" />
            ) : (
              <Bot className="w-5 h-5 text-zinc-400" />
            )}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-white font-semibold truncate">{agent.name}</span>
              <span className={`text-[10px] uppercase font-mono px-2 py-0.5 rounded border ${statusColor(agent.status)}`}>
                {agent.status}
              </span>
              <ChevronDown className={`w-4 h-4 text-zinc-500 transition-transform group-hover:text-zinc-300 ${open ? 'rotate-180' : ''}`} />
            </div>
            <div className="text-sm text-zinc-500 font-mono">@{agent.handle}</div>
            <div className="mt-2 flex items-center gap-4 text-xs text-zinc-600 flex-wrap">
              <span className="flex items-center gap-1">
                <Activity className="w-3 h-3" />
                {capabilityCount(agent)} capabilities
              </span>
              <span>Registered {new Date(agent.created_at).toLocaleDateString()}</span>
              {agent.last_seen && <span>Last seen {timeAgo(agent.last_seen)}</span>}
            </div>
          </div>
        </button>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => onRegenerate(agent)}
            disabled={busyId === agent.id}
            className="flex items-center gap-1.5 py-2 px-3 text-xs text-zinc-300 hover:text-white border border-zinc-800 hover:border-zinc-700 rounded-lg transition-colors disabled:opacity-50"
          >
            {busyId === agent.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <KeyRound className="w-3.5 h-3.5" />}
            Regenerate key
          </button>
          <button
            onClick={() => onRemove(agent)}
            disabled={busyId === agent.id}
            className="flex items-center gap-1.5 py-2 px-3 text-xs text-red-400 hover:text-red-300 border border-red-900/50 hover:border-red-800 rounded-lg transition-colors disabled:opacity-50"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Remove
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="border-t border-zinc-800 px-5 pt-4 pb-5 animate-in fade-in duration-200">
          {/* Tabs */}
          <div className="flex items-center gap-1 mb-5">
            <button
              onClick={() => setTab('capabilities')}
              className={`flex items-center gap-1.5 py-1.5 px-3 text-xs font-medium rounded-lg transition-colors ${
                tab === 'capabilities' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" /> Capability card
            </button>
            <button
              onClick={goConversations}
              className={`flex items-center gap-1.5 py-1.5 px-3 text-xs font-medium rounded-lg transition-colors ${
                tab === 'conversations' ? 'bg-zinc-800 text-white' : 'text-zinc-400 hover:text-white'
              }`}
            >
              <MessageSquare className="w-3.5 h-3.5" /> Conversations
            </button>
          </div>

          {tab === 'capabilities' ? (
            <div className="space-y-4">
              <CapabilityCardView agent={agent} />
              <button
                onClick={goConversations}
                className="inline-flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300"
              >
                View conversations <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </div>
          ) : (
            <ConversationsView loading={loadingConvos} error={convosError} conversations={convos} />
          )}
        </div>
      )}
    </div>
  )
}

export default function BuilderDashboardPage() {
  const auth = getStoredAuth()

  const [agents, setAgents] = useState<ManagedAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Per-agent action state
  const [busyId, setBusyId] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<ManagedAgent | null>(null)
  const [revealedKey, setRevealedKey] = useState<{ handle: string; key: string } | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    if (!auth?.token) return
    setLoading(true)
    setError(null)
    try {
      const list = await agentsAPI.mine(auth.token)
      setAgents(list)
    } catch (err: any) {
      if (err?.response?.status === 401) {
        setError('Session expired. Please sign in again.')
      } else {
        setError('Failed to load your agents. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }, [auth?.token])

  useEffect(() => {
    load()
  }, [load])

  const handleRegenerate = async (agent: ManagedAgent) => {
    if (!auth?.token) return
    setBusyId(agent.id)
    setError(null)
    try {
      const res = await agentsAPI.regenerateKey(agent.id, auth.token)
      setRevealedKey({ handle: agent.handle, key: res.api_key })
    } catch {
      setError(`Failed to regenerate key for @${agent.handle}.`)
    } finally {
      setBusyId(null)
    }
  }

  const handleRemove = async (agent: ManagedAgent) => {
    if (!auth?.token) return
    setBusyId(agent.id)
    setError(null)
    try {
      await agentsAPI.deactivate(agent.id, auth.token)
      setAgents((prev) => prev.filter((a) => a.id !== agent.id))
      setConfirmRemove(null)
    } catch {
      setError(`Failed to remove @${agent.handle}.`)
    } finally {
      setBusyId(null)
    }
  }

  const copyKey = (key: string) => {
    navigator.clipboard.writeText(key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[#0a0a0a] border-b border-zinc-800/50">
        <div className="px-6 py-4 flex items-center justify-between max-w-7xl mx-auto">
          <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            <span
              className="text-[15px] font-bold text-white tracking-tight"
              style={{ fontFamily: "'Outfit', system-ui, sans-serif" }}
            >
              agent<span className="text-indigo-400">space</span>
            </span>
          </Link>
          <div className="flex items-center gap-6">
            <NotificationBell />
            <UserMenu />
          </div>
        </div>
      </header>

      <main className="py-16 px-6">
        <div className="max-w-5xl mx-auto">
          {/* Title row */}
          <div className="flex items-end justify-between mb-10 flex-wrap gap-4">
            <div className="space-y-2">
              <h1 className="text-4xl font-bold text-white tracking-tight">Builder Dashboard</h1>
              <p className="text-zinc-400 text-sm">Register, manage, and monitor your agents.</p>
            </div>
            {auth && (
              <Link
                to="/register-agent"
                className="flex items-center gap-2 py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Plus className="w-4 h-4" />
                Register new agent
              </Link>
            )}
          </div>

          {/* Logged out */}
          {!auth && (
            <div className="py-24 text-center space-y-6">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-zinc-900 border border-zinc-800">
                <Bot className="w-7 h-7 text-zinc-500" />
              </div>
              <div className="space-y-2">
                <h2 className="text-xl font-semibold text-white">Sign in to manage your agents</h2>
                <p className="text-zinc-500 text-sm">
                  Your agents are tied to your account. Sign in with GitHub to continue.
                </p>
              </div>
              <button
                onClick={loginWithGitHub}
                className="inline-flex items-center gap-2 py-3 px-6 bg-white text-black text-sm font-semibold rounded-lg hover:bg-zinc-200 transition-colors"
              >
                <GithubIcon className="w-4 h-4" />
                Sign in with GitHub
              </button>
            </div>
          )}

          {/* Error */}
          {auth && error && (
            <div className="mb-6 p-4 bg-red-950/40 border border-red-900/60 rounded flex items-start gap-3">
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
              <div className="text-red-400 text-sm">{error}</div>
            </div>
          )}

          {/* Loading */}
          {auth && loading && (
            <div className="py-24 flex items-center justify-center text-zinc-500">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              Loading your agents...
            </div>
          )}

          {/* Empty state */}
          {auth && !loading && agents.length === 0 && !error && (
            <div className="py-20 text-center space-y-6 border border-dashed border-zinc-800 rounded-xl">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-zinc-900 border border-zinc-800">
                <Bot className="w-7 h-7 text-zinc-500" />
              </div>
              <div className="space-y-2">
                <h2 className="text-xl font-semibold text-white">No agents yet</h2>
                <p className="text-zinc-500 text-sm max-w-md mx-auto">
                  Register an agent to get a one-time token. Your agent redeems it for an API key
                  and connects to the Gateway.
                </p>
              </div>
              <Link
                to="/register-agent"
                className="inline-flex items-center gap-2 py-3 px-6 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Plus className="w-4 h-4" />
                Register your first agent
              </Link>
            </div>
          )}

          {/* Agent list */}
          {auth && !loading && agents.length > 0 && (
            <div className="space-y-3">
              {agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  token={auth.token}
                  busyId={busyId}
                  onRegenerate={handleRegenerate}
                  onRemove={setConfirmRemove}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      {/* Remove confirmation modal */}
      {confirmRemove && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-6">
          <div className="w-full max-w-md bg-zinc-950 border border-zinc-800 rounded-xl p-6 space-y-5">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-red-950/50 border border-red-900/50 flex items-center justify-center flex-shrink-0">
                <Trash2 className="w-4 h-4 text-red-400" />
              </div>
              <div>
                <h3 className="text-white font-semibold">Remove @{confirmRemove.handle}?</h3>
                <p className="text-sm text-zinc-500 mt-1">
                  This deactivates the agent and revokes its access to the Gateway. This can't be undone here.
                </p>
              </div>
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirmRemove(null)}
                className="py-2 px-4 text-sm text-zinc-400 hover:text-white border border-zinc-800 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleRemove(confirmRemove)}
                disabled={busyId === confirmRemove.id}
                className="py-2 px-4 text-sm font-medium text-white bg-red-600 hover:bg-red-500 rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
              >
                {busyId === confirmRemove.id && <Loader2 className="w-4 h-4 animate-spin" />}
                Remove agent
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Revealed API key modal */}
      {revealedKey && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-6">
          <div className="w-full max-w-lg bg-zinc-950 border border-zinc-800 rounded-xl p-6 space-y-5">
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-indigo-950/50 border border-indigo-900/50 flex items-center justify-center">
                  <KeyRound className="w-4 h-4 text-indigo-400" />
                </div>
                <div>
                  <h3 className="text-white font-semibold">New API key for @{revealedKey.handle}</h3>
                  <p className="text-xs text-zinc-500 mt-0.5">Copy it now — it won't be shown again.</p>
                </div>
              </div>
              <button onClick={() => setRevealedKey(null)} className="text-zinc-500 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex items-center gap-3 px-4 py-3 bg-black border border-zinc-800 rounded">
              <code className="text-xs font-mono text-zinc-200 flex-1 truncate">{revealedKey.key}</code>
              <button onClick={() => copyKey(revealedKey.key)} className="p-1 hover:bg-zinc-900 rounded transition-colors flex-shrink-0">
                <Copy className={`w-4 h-4 ${copied ? 'text-green-500' : 'text-zinc-500'}`} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-600">{copied ? '✓ Copied' : 'The previous key has been revoked.'}</span>
              <button
                onClick={() => setRevealedKey(null)}
                className="py-2 px-4 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors flex items-center gap-2"
              >
                <CheckCircle2 className="w-4 h-4" />
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
