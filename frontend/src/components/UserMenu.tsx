import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getStoredAuth, clearAuth, loginWithGitHub, isAdmin } from '../services/api'

/**
 * Compact user menu for the site header.
 * - Logged out: shows a GitHub icon button that triggers OAuth login.
 * - Logged in: shows the user's avatar; click opens a dropdown with
 *   username, admin badge (if applicable), and sign-out.
 */
export default function UserMenu() {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const auth = getStoredAuth()
  const admin = isAdmin()

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // --- Logged out: GitHub icon button ---
  if (!auth) {
    return (
      <button
        onClick={loginWithGitHub}
        className="flex items-center justify-center w-9 h-9 sm:w-8 sm:h-8 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-all"
        title="Sign in with GitHub"
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
        </svg>
      </button>
    )
  }

  // --- Logged in: avatar + dropdown ---
  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-lg hover:bg-zinc-800 transition-all px-1.5 py-1.5 sm:px-1 sm:py-1"
      >
        <img
          src={auth.user.avatar_url}
          alt={auth.user.login}
          className="w-7 h-7 rounded-full ring-2 ring-zinc-700"
        />
        {admin && (
          <span className="w-2 h-2 rounded-full bg-indigo-500 absolute -top-0.5 -right-0.5" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-48 sm:w-52 bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl shadow-black/50 overflow-hidden" style={{ zIndex: 10000 }}>
          <div className="px-4 py-3 border-b border-zinc-800">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-white truncate">
                {auth.user.name || auth.user.login}
              </span>
              {admin && (
                <span className="text-[10px] font-semibold px-1.5 py-0.5 bg-indigo-500/20 text-indigo-400 rounded-full uppercase tracking-wide">
                  Admin
                </span>
              )}
            </div>
            <div className="text-xs text-zinc-500 truncate">@{auth.user.login}</div>
          </div>
          <Link
            to={`/${auth.user.login}`}
            onClick={() => setOpen(false)}
            className="block w-full text-left px-4 py-2.5 text-sm text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors"
          >
            My Profile
          </Link>
          <button
            onClick={() => {
              clearAuth()
              window.location.reload()
            }}
            className="w-full text-left px-4 py-2.5 text-sm text-zinc-300 hover:text-white hover:bg-zinc-800 transition-colors border-t border-zinc-800"
          >
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
