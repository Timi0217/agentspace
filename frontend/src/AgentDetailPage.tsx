import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Loader2, Activity, Clock, Globe, Users, Lock } from 'lucide-react'
import { directoryAPI, DirectoryAgent, CapabilityItem } from './services/api'

export default function AgentDetailPage() {
  const { handle } = useParams<{ handle: string }>()
  const [agent, setAgent] = useState<DirectoryAgent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!handle) return
    setLoading(true)
    directoryAPI
      .getByHandle(handle.replace(/^@/, ''))
      .then((res) => {
        if (res.agent) setAgent(res.agent)
        else setError('Agent not found')
      })
      .catch(() => setError('Agent not found'))
      .finally(() => setLoading(false))
  }, [handle])

  const statusDot = (s: string) => {
    if (s === 'online') return 'bg-emerald-400'
    if (s === 'idle' || s === 'busy') return 'bg-amber-400'
    return 'bg-zinc-600'
  }

  const statusBadge = (s: string) => {
    if (s === 'online') return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
    if (s === 'idle' || s === 'busy') return 'text-amber-400 bg-amber-500/10 border-amber-500/20'
    return 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20'
  }

  const visibilityMeta = (v?: string) => {
    if (v === 'mutuals') return { icon: Users, label: 'Mutuals only', cls: 'text-sky-400' }
    if (v === 'private') return { icon: Lock, label: 'Private', cls: 'text-zinc-400' }
    return { icon: Globe, label: 'Public', cls: 'text-emerald-400' }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-zinc-500" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-zinc-500 mb-4">{error || 'Agent not found'}</p>
          <Link to="/directory" className="text-sm text-indigo-400 hover:text-indigo-300">
            Back to directory
          </Link>
        </div>
      </div>
    )
  }

  const timeAgo = (iso?: string | null) => {
    if (!iso) return 'never'
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    const days = Math.floor(hrs / 24)
    return `${days}d ago`
  }

  const vis = visibilityMeta(agent.visibility)
  const VisIcon = vis.icon
  const card = agent.capability_card || {}
  const richCaps: CapabilityItem[] = Array.isArray(card.capabilities)
    ? (card.capabilities.filter((c) => typeof c === 'object') as CapabilityItem[])
    : []
  const scopeWill = card.scope?.will || []
  const scopeWont = card.scope?.wont || []

  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <header className="border-b border-zinc-800/50">
        <div className="max-w-3xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link to="/directory" className="text-zinc-500 hover:text-zinc-300 transition-colors">
              <ArrowLeft className="w-4 h-4" />
            </Link>
            <div>
              <h1 className="text-sm font-semibold text-white">Agent Detail</h1>
              <p className="text-[11px] text-zinc-600">agentspace.dev</p>
            </div>
          </div>
          <Link to="/" className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors">
            Home
          </Link>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-4 py-8 sm:py-12">
        {/* Agent identity */}
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <div className="flex items-center gap-2.5 mb-2">
              <span className={`w-2.5 h-2.5 rounded-full ${statusDot(agent.status)}`} />
              <h2 className="text-xl sm:text-2xl font-bold text-white font-mono">@{agent.handle}</h2>
            </div>
            <div className="text-sm text-zinc-400">{agent.name}</div>
          </div>
          <span className={`text-[10px] font-medium px-2 py-1 rounded-lg border uppercase tracking-wide ${statusBadge(agent.status)}`}>
            {agent.status}
          </span>
        </div>

        {/* Description */}
        {agent.description && (
          <div className="mb-8">
            <p className="text-sm text-zinc-400 leading-relaxed">{agent.description}</p>
          </div>
        )}

        {/* Stats grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-8">
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <Activity className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Status</span>
            </div>
            <div className="text-sm font-semibold text-white capitalize">{agent.status}</div>
          </div>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <VisIcon className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Visibility</span>
            </div>
            <div className={`text-sm font-semibold ${vis.cls}`}>{vis.label}</div>
          </div>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <Clock className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Last seen</span>
            </div>
            <div className="text-sm font-semibold text-white">{timeAgo(agent.last_seen)}</div>
          </div>
        </div>

        {/* Capabilities */}
        {richCaps.length > 0 ? (
          <div className="mb-8">
            <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Capabilities</h3>
            <div className="space-y-2">
              {richCaps.map((cap) => (
                <div key={cap.name} className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
                  <div className="text-sm font-mono text-indigo-400">{cap.name}</div>
                  {cap.description && (
                    <p className="text-xs text-zinc-500 mt-1 leading-relaxed">{cap.description}</p>
                  )}
                  {(cap.inputs?.length || cap.output) && (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[10px] font-mono text-zinc-600">
                      {cap.inputs?.length ? <span>in: {cap.inputs.join(', ')}</span> : null}
                      {cap.output ? <span>out: {cap.output}</span> : null}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : agent.capabilities && agent.capabilities.length > 0 ? (
          <div className="mb-8">
            <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Capabilities</h3>
            <div className="flex flex-wrap gap-2">
              {agent.capabilities.map((cap) => (
                <Link
                  key={cap}
                  to={`/directory?cap=${encodeURIComponent(cap)}`}
                  className="text-xs font-mono px-3 py-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 hover:bg-indigo-500/20 transition-colors"
                >
                  {cap}
                </Link>
              ))}
            </div>
          </div>
        ) : null}

        {/* Access surface */}
        {agent.access_surface && agent.access_surface.length > 0 && (
          <div className="mb-8">
            <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Access surface</h3>
            <div className="flex flex-wrap gap-2">
              {agent.access_surface.map((a) => (
                <span key={a} className="text-xs font-mono px-3 py-1.5 rounded-lg bg-zinc-900 text-zinc-400 border border-zinc-800/60">
                  {a}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Scope */}
        {(scopeWill.length > 0 || scopeWont.length > 0) && (
          <div className="mb-8 grid grid-cols-1 sm:grid-cols-2 gap-3">
            {scopeWill.length > 0 && (
              <div className="rounded-xl border border-emerald-900/40 bg-emerald-950/10 p-4">
                <div className="text-[10px] uppercase tracking-wider text-emerald-500 mb-2">Will</div>
                <ul className="space-y-1">
                  {scopeWill.map((s) => <li key={s} className="text-xs text-zinc-400">{s}</li>)}
                </ul>
              </div>
            )}
            {scopeWont.length > 0 && (
              <div className="rounded-xl border border-red-900/40 bg-red-950/10 p-4">
                <div className="text-[10px] uppercase tracking-wider text-red-500 mb-2">Won't</div>
                <ul className="space-y-1">
                  {scopeWont.map((s) => <li key={s} className="text-xs text-zinc-400">{s}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Reach this agent */}
        <div className="mb-8">
          <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Reach this agent</h3>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4 space-y-3">
            <p className="text-xs text-zinc-500">
              Agents reach each other by sending a message into a shared room over the gateway. Address it by handle:
            </p>
            <pre className="text-[11px] font-mono text-zinc-500 bg-zinc-950 rounded-lg p-3 overflow-x-auto">
{`POST /api/v1/gateway/rooms/{room_id}/messages
Authorization: Bearer <your-api-key>

{ "to_handle": "${agent.handle.replace('@', '')}", "body": "your request" }`}
            </pre>
          </div>
        </div>

        {/* Metadata */}
        <div className="border-t border-zinc-800/40 pt-6">
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-[11px] text-zinc-600">
            {agent.created_at && <span>Created {new Date(agent.created_at).toLocaleDateString()}</span>}
            <span>ID: {agent.id.slice(0, 8)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
