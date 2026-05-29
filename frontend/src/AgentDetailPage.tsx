import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Loader2, ExternalLink, Clock, Activity, Zap } from 'lucide-react'
import { registryAPI, RegistryAgent } from './services/api'

export default function AgentDetailPage() {
  const { handle } = useParams<{ handle: string }>()
  const [agent, setAgent] = useState<RegistryAgent | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!handle) return
    setLoading(true)
    registryAPI
      .getAgent(handle.replace(/^@/, ''))
      .then((res) => setAgent(res.agent))
      .catch(() => setError('Agent not found'))
      .finally(() => setLoading(false))
  }, [handle])

  const statusDot = (s: string) => {
    if (s === 'online') return 'bg-emerald-400'
    if (s === 'probation') return 'bg-amber-400'
    return 'bg-zinc-600'
  }

  const statusBadge = (s: string) => {
    if (s === 'online') return 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20'
    if (s === 'probation') return 'text-amber-400 bg-amber-500/10 border-amber-500/20'
    return 'text-zinc-500 bg-zinc-500/10 border-zinc-500/20'
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

  const timeAgo = (iso: string | null) => {
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
              <h2 className="text-xl sm:text-2xl font-bold text-white font-mono">{agent.handle}</h2>
            </div>
            <div className="text-sm text-zinc-400">{agent.name}</div>
            {agent.builder_name && (
              <div className="text-xs text-zinc-600 mt-1">Built by {agent.builder_name}</div>
            )}
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
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <Activity className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Status</span>
            </div>
            <div className="text-sm font-semibold text-white capitalize">{agent.status}</div>
          </div>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <Zap className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Latency</span>
            </div>
            <div className="text-sm font-semibold text-white">
              {agent.last_probe_latency_ms != null ? `${agent.last_probe_latency_ms}ms` : '--'}
            </div>
          </div>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <ExternalLink className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Relay calls</span>
            </div>
            <div className="text-sm font-semibold text-white">{agent.total_relay_calls.toLocaleString()}</div>
          </div>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
            <div className="flex items-center gap-1.5 text-zinc-600 mb-2">
              <Clock className="w-3 h-3" />
              <span className="text-[10px] uppercase tracking-wide">Last probe</span>
            </div>
            <div className="text-sm font-semibold text-white">{timeAgo(agent.last_probe_at)}</div>
          </div>
        </div>

        {/* Capabilities */}
        {agent.capabilities && agent.capabilities.length > 0 && (
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
        )}

        {/* Pricing */}
        {agent.pricing && (
          <div className="mb-8">
            <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Pricing</h3>
            <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4">
              <span className="text-sm text-zinc-300">{agent.pricing}</span>
              {agent.price_per_call_usd && (
                <span className="text-xs text-zinc-600 ml-2">({agent.price_per_call_usd} per call)</span>
              )}
            </div>
          </div>
        )}

        {/* Integration info */}
        <div className="mb-8">
          <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider mb-3">Use this agent</h3>
          <div className="rounded-xl border border-zinc-800/60 bg-zinc-900/30 p-4 space-y-3">
            <div>
              <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1">Relay endpoint</div>
              <code className="text-xs font-mono text-zinc-400 break-all">
                POST /api/v1/registry/relay
              </code>
            </div>
            <div className="border-t border-zinc-800/40 pt-3">
              <div className="text-[10px] text-zinc-600 uppercase tracking-wider mb-1.5">Example payload</div>
              <pre className="text-[11px] font-mono text-zinc-500 bg-zinc-950 rounded-lg p-3 overflow-x-auto">
{`{
  "from_handle": "your-agent",
  "to_handle": "${agent.handle.replace('@', '')}",
  "message": {
    "request": "your query here"
  }
}`}
              </pre>
            </div>
          </div>
        </div>

        {/* Metadata */}
        <div className="border-t border-zinc-800/40 pt-6">
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-[11px] text-zinc-600">
            {agent.is_chekk_native && (
              <span className="text-indigo-500">Chekk Native Agent</span>
            )}
            <span>Created {new Date(agent.created_at).toLocaleDateString()}</span>
            <span>ID: {agent.id.slice(0, 8)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
