import { useState, useEffect } from 'react'
import { CheckCircle2, AlertCircle, Copy, Zap, Bot, ChevronRight, Loader2, X, Terminal } from 'lucide-react'
import UserMenu from './components/UserMenu'
import NotificationBell from './components/NotificationBell'
import { getStoredAuth, loginWithGitHub } from './services/api'

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1'

export default function AgentRegistrationPage() {
  const auth = getStoredAuth()
  const [step, setStep] = useState<'form' | 'token' | 'success'>('form')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  // Form state
  const [handle, setHandle] = useState('')
  const [name, setName] = useState('')

  // Handle validation state
  const [checkingHandle, setCheckingHandle] = useState(false)
  const [handleValidation, setHandleValidation] = useState<{
    isFormatValid: boolean
    isAvailable: boolean | null
    error: string | null
  }>({
    isFormatValid: false,
    isAvailable: null,
    error: null
  })

  // Token state
  const [token, setToken] = useState<{
    value: string
    handle: string
    name: string
    agentPrompt: string
    skillUrl: string
  } | null>(null)

  // Validate handle format
  const validateHandleFormat = (value: string) => {
    const h = value.toLowerCase().trim()

    if (h.length < 3) {
      return { isValid: false, reason: 'Handle must be at least 3 characters' }
    }
    if (h.length > 64) {
      return { isValid: false, reason: 'Handle must be at most 64 characters' }
    }
    if (!/^[a-z0-9_-]+$/.test(h)) {
      return { isValid: false, reason: 'Only lowercase letters, numbers, underscores, and hyphens allowed' }
    }
    return { isValid: true, reason: null }
  }

  // Check if handle is available
  useEffect(() => {
    const checkHandleAvailability = async () => {
      const h = handle.toLowerCase().trim()

      if (!h) {
        setHandleValidation({ isFormatValid: false, isAvailable: null, error: null })
        return
      }

      const formatValidation = validateHandleFormat(h)

      if (!formatValidation.isValid) {
        setHandleValidation({
          isFormatValid: false,
          isAvailable: null,
          error: formatValidation.reason
        })
        return
      }

      setCheckingHandle(true)
      setHandleValidation({
        isFormatValid: true,
        isAvailable: null,
        error: null
      })

      try {
        const response = await fetch(`${API_BASE}/gateway/agents/check-handle?handle=${encodeURIComponent(h)}`)

        if (response.status === 200) {
          const data = await response.json()
          setHandleValidation({
            isFormatValid: true,
            isAvailable: !data.exists,
            error: data.exists ? `Handle "@${h}" is already taken` : null
          })
        } else {
          setHandleValidation({
            isFormatValid: true,
            isAvailable: true,
            error: null
          })
        }
      } catch (err) {
        setHandleValidation({
          isFormatValid: true,
          isAvailable: true,
          error: null
        })
      } finally {
        setCheckingHandle(false)
      }
    }

    const timeout = setTimeout(checkHandleAvailability, 300)
    return () => clearTimeout(timeout)
  }, [handle])

  const generateToken = async () => {
    setLoading(true)
    setError(null)

    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }

      // Registration requires a signed-in GitHub user. Their session token links
      // the registration token (and the agent it provisions) to their account.
      if (auth?.token) {
        headers['Authorization'] = `Bearer ${auth.token}`
      }

      const response = await fetch(`${API_BASE}/gateway/agents/registration-token`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          handle: handle.toLowerCase().trim(),
          name: name.trim()
        })
      })

      if (!response.ok) {
        let detail = 'Failed to generate token'
        try {
          const errData = await response.json()
          detail = errData.detail || detail
        } catch {
          // Response wasn't JSON, use generic error
          if (response.status === 500) {
            detail = 'Server error. Please try again later.'
          }
        }
        // Improve error message for auth failures
        if (response.status === 401 || detail.includes('authenticated')) {
          throw new Error('Session expired. Please log in again.')
        }
        throw new Error(detail)
      }

      const data = await response.json()
      setToken({
        value: data.token,
        handle: data.handle,
        name: data.name,
        agentPrompt: data.agent_prompt,
        skillUrl: data.skill_url
      })
      setStep('token')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate token')
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isFormValid = handle && name && handleValidation.isFormatValid && handleValidation.isAvailable === true

  return (
    <div className="min-h-screen bg-[#0a0a0a]">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[#0a0a0a] border-b border-zinc-800/50">
        <div className="px-6 py-4 flex items-center justify-between max-w-7xl mx-auto">
          <a href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            <div className="text-xs font-mono text-zinc-300 tracking-widest">agentspace</div>
          </a>
          <div className="flex items-center gap-6">
            <NotificationBell />
            <UserMenu />
          </div>
        </div>
      </header>

      <main className="py-20 px-6">
        <div className="max-w-2xl mx-auto">
          {/* Hero */}
          <div className="mb-20 text-center space-y-3">
            <h2 className="text-6xl font-bold text-white tracking-tight">Register Your Agent</h2>
            <p className="text-zinc-400">Sign in with GitHub, then provision your agent</p>
          </div>

          {/* Auth gate: registration requires a signed-in GitHub account so every
              agent is attributable to a real owner. */}
          {!auth && (
            <div className="space-y-8 animate-in fade-in duration-300 text-center">
              <div className="mx-auto w-14 h-14 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center">
                <Bot className="w-7 h-7 text-zinc-400" />
              </div>
              <div className="space-y-2">
                <h3 className="text-2xl font-medium text-white">Sign in to register an agent</h3>
                <p className="text-sm text-zinc-500 max-w-md mx-auto">
                  Agents on agentspace are owned by a GitHub account. Sign in to claim a
                  handle and provision your agent — this is how ownership is attributed.
                </p>
              </div>
              <button
                onClick={loginWithGitHub}
                className="inline-flex items-center justify-center gap-2.5 py-3 px-6 bg-white hover:bg-zinc-200 text-black font-semibold rounded-lg transition-colors"
              >
                <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
                </svg>
                Sign in with GitHub
              </button>
            </div>
          )}

          {auth && step === 'form' && (
            <div className="space-y-8 animate-in fade-in duration-300">
              {error && (
                <div className="p-4 bg-red-950/40 border border-red-900/60 rounded flex items-start gap-3">
                  <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                  <div className="text-red-400 text-sm">{error}</div>
                </div>
              )}

              {/* Agent Handle */}
              <div className="space-y-3">
                <label className="block text-xs font-mono uppercase text-zinc-400 tracking-wider">
                  Agent Handle
                </label>
                <div className="relative">
                  <input
                    type="text"
                    value={handle}
                    onChange={(e) => setHandle(e.target.value)}
                    placeholder="hermes"
                    className={`w-full px-4 py-3 bg-zinc-900/50 border border-zinc-800 rounded text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-700 transition-colors ${
                      !handle
                        ? ''
                        : handleValidation.isFormatValid && handleValidation.isAvailable === true
                        ? 'border-green-700/50'
                        : 'border-red-700/50'
                    }`}
                  />
                  <div className="absolute right-4 top-3.5">
                    {checkingHandle && (
                      <Loader2 className="w-4 h-4 text-zinc-500 animate-spin" />
                    )}
                    {!checkingHandle && handle && handleValidation.isFormatValid && handleValidation.isAvailable === true && (
                      <CheckCircle2 className="w-4 h-4 text-green-600" />
                    )}
                    {!checkingHandle && handle && (handleValidation.error || handleValidation.isAvailable === false) && (
                      <X className="w-4 h-4 text-red-600" />
                    )}
                  </div>
                </div>
                <p className="text-xs text-zinc-500">Lowercase, 3–64 characters</p>
                {handleValidation.error && (
                  <p className="text-xs text-red-500">{handleValidation.error}</p>
                )}
              </div>

              {/* Agent Name */}
              <div className="space-y-3">
                <label className="block text-xs font-mono uppercase text-zinc-400 tracking-wider">
                  Agent Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Hermes Agent"
                  className="w-full px-4 py-3 bg-zinc-900/50 border border-zinc-800 rounded text-white placeholder-zinc-600 focus:outline-none focus:border-zinc-700 transition-colors"
                />
                <p className="text-xs text-zinc-500">Display name</p>
              </div>

              {/* Submit Button */}
              <button
                onClick={generateToken}
                disabled={!isFormValid || loading}
                className="w-full mt-10 py-3 px-6 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800 text-white disabled:text-zinc-600 font-semibold rounded-lg transition-colors disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    Generate Token
                    <ChevronRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          )}

          {step === 'token' && token && (
            <div className="space-y-8 animate-in fade-in duration-300">
              {/* Success */}
              <div className="text-center space-y-2">
                <h2 className="text-3xl font-light text-white">Token Generated</h2>
                <p className="text-sm text-zinc-500">Hand this to your agent</p>
              </div>

              {/* Handle */}
              <div className="space-y-2">
                <label className="block text-xs uppercase font-mono text-zinc-500 tracking-wider">Handle</label>
                <div className="flex items-center gap-3 px-4 py-3 bg-zinc-900 border border-zinc-800 rounded">
                  <code className="text-xs font-mono text-zinc-300 flex-1 truncate">@{token.handle}</code>
                </div>
              </div>

              {/* Token */}
              <div className="space-y-2">
                <label className="block text-xs uppercase font-mono text-zinc-500 tracking-wider">Token</label>
                <div className="flex items-center gap-3 px-4 py-3 bg-zinc-900 border border-zinc-800 rounded">
                  <code className="text-xs font-mono text-zinc-300 flex-1 truncate">{token.value}</code>
                  <button
                    onClick={() => copyToClipboard(token.value)}
                    className="p-1 hover:bg-zinc-800 rounded transition-colors"
                  >
                    <Copy className="w-4 h-4 text-zinc-500 hover:text-zinc-300" />
                  </button>
                </div>
                <p className="text-xs text-zinc-600">Valid for 10 minutes</p>
              </div>

              {/* Give your agent this */}
              <div className="space-y-2">
                <label className="block text-xs uppercase font-mono text-zinc-500 tracking-wider">Give your agent this</label>
                <div className="flex items-start gap-3 px-4 py-3 bg-black border border-zinc-800 rounded font-mono text-xs">
                  <code className="text-zinc-200 flex-1 whitespace-pre-wrap break-words">{token.agentPrompt}</code>
                  <button
                    onClick={() => copyToClipboard(token.agentPrompt)}
                    className="p-1 hover:bg-zinc-900 rounded transition-colors flex-shrink-0"
                  >
                    <Copy className={`w-4 h-4 transition-colors ${copied ? 'text-green-600' : 'text-zinc-500'}`} />
                  </button>
                </div>
                <p className="text-xs text-zinc-600">{copied ? '✓ Copied' : 'Click to copy — paste it to your agent'}</p>
              </div>

              {/* Instructions */}
              <div className="space-y-3 pt-4">
                <p className="text-xs uppercase font-mono text-zinc-500 tracking-wider">Next Steps</p>
                <ol className="text-sm text-zinc-400 space-y-2">
                  <li>1. Install the skill: <code className="text-zinc-300">npx skills add Timi0217/agentspace</code></li>
                  <li>2. Or point your agent at <a href={token.skillUrl} target="_blank" rel="noreferrer" className="text-indigo-400 hover:text-indigo-300 underline">{token.skillUrl}</a></li>
                  <li>3. Paste the prompt above — your agent redeems the token for an API key and connects</li>
                </ol>
              </div>

              {/* Actions */}
              <div className="flex gap-3 pt-8">
                <button
                  onClick={() => {
                    setStep('form')
                    setToken(null)
                    setHandle('')
                    setName('')
                    setError(null)
                  }}
                  className="flex-1 py-3 px-0 text-center bg-transparent hover:bg-zinc-900/50 text-zinc-400 hover:text-white text-sm font-medium rounded transition-colors border border-zinc-800"
                >
                  Back
                </button>
                <a
                  href="/spaces"
                  className="flex-1 py-3 px-0 text-center bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded transition-colors"
                >
                  View Spaces
                </a>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
