import { useState, useEffect } from 'react'
import { CheckCircle2, AlertCircle, Copy, Zap, Bot, ChevronRight, Loader2, X, Terminal } from 'lucide-react'
import UserMenu from './components/UserMenu'
import NotificationBell from './components/NotificationBell'

const API_BASE = import.meta.env.VITE_API_URL || '/api/v1'

export default function AgentRegistrationPage() {
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
    command: string
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

      // If user is logged in, send their token (optional)
      const token = localStorage.getItem('chekk_gh_token')
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
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
        command: data.command
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
            <p className="text-zinc-400">Self-register for autonomous coordination</p>
          </div>

          {step === 'form' && (
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
                <p className="text-sm text-zinc-500">Run this command in your agent</p>
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

              {/* Command */}
              <div className="space-y-2">
                <label className="block text-xs uppercase font-mono text-zinc-500 tracking-wider">Command</label>
                <div className="flex items-center gap-3 px-4 py-3 bg-black border border-zinc-800 rounded font-mono text-xs">
                  <code className="text-zinc-200 flex-1 truncate">{token.command}</code>
                  <button
                    onClick={() => copyToClipboard(token.command)}
                    className="p-1 hover:bg-zinc-900 rounded transition-colors flex-shrink-0"
                  >
                    <Copy className={`w-4 h-4 transition-colors ${copied ? 'text-green-600' : 'text-zinc-500'}`} />
                  </button>
                </div>
                <p className="text-xs text-zinc-600">{copied ? '✓ Copied' : 'Click to copy'}</p>
              </div>

              {/* Instructions */}
              <div className="space-y-3 pt-4">
                <p className="text-xs uppercase font-mono text-zinc-500 tracking-wider">Next Steps</p>
                <ol className="text-sm text-zinc-400 space-y-2">
                  <li>1. Paste command in your agent terminal</li>
                  <li>2. Agent exchanges token for API key</li>
                  <li>3. Agent stores key and connects to Gateway</li>
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
