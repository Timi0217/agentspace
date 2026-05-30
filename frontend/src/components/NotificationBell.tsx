import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bell, UserPlus } from 'lucide-react'
import { getStoredAuth, notificationAPI, type NotificationItem } from '../services/api'

function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const menuRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  const auth = getStoredAuth()

  // Poll for the pending-request count every 30s.
  const fetchCount = useCallback(() => {
    if (!auth) return
    notificationAPI.count(auth.token).then((d) => setUnreadCount(d.unread_count)).catch(() => {})
  }, [auth?.token])

  useEffect(() => {
    fetchCount()
    const interval = setInterval(fetchCount, 30000)
    return () => clearInterval(interval)
  }, [fetchCount])

  // Fetch the full list when opening.
  useEffect(() => {
    if (!open || !auth) return
    notificationAPI.list(auth.token, 30).then(setNotifications).catch(() => {})
  }, [open, auth?.token])

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (!auth) return null

  const goToRequests = () => {
    setOpen(false)
    navigate('/builder?tab=requests')
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        onClick={() => setOpen(!open)}
        className="relative flex items-center justify-center w-9 h-9 sm:w-8 sm:h-8 rounded-lg text-zinc-400 hover:text-white hover:bg-zinc-800 transition-all"
        title="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] flex items-center justify-center text-[10px] font-bold text-white bg-indigo-500 rounded-full px-1">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="fixed left-4 right-4 sm:left-auto sm:right-0 sm:absolute top-14 sm:top-full sm:mt-2 sm:w-80 bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl shadow-black/50 overflow-hidden"
          style={{ zIndex: 10000 }}
        >
          <div className="px-4 py-3 border-b border-zinc-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Connection requests</span>
            {notifications.length > 0 && (
              <button onClick={goToRequests} className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                Review all
              </button>
            )}
          </div>

          <div className="max-h-[60vh] sm:max-h-96 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center">
                <Bell className="w-8 h-8 text-zinc-700 mx-auto mb-2" />
                <p className="text-sm text-zinc-600">No pending requests</p>
              </div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={goToRequests}
                  className="w-full text-left flex items-start gap-3 px-3 py-2.5 sm:px-4 sm:py-3 hover:bg-zinc-800/50 transition-colors border-b border-zinc-800/30 last:border-0 bg-indigo-500/5"
                >
                  <div className="relative flex-shrink-0">
                    {n.actor_avatar_url ? (
                      <img src={n.actor_avatar_url} alt={n.actor_handle || ''} className="w-8 h-8 rounded-full" />
                    ) : (
                      <div className="w-8 h-8 rounded-full bg-zinc-800 flex items-center justify-center">
                        <UserPlus className="w-4 h-4 text-zinc-400" />
                      </div>
                    )}
                    <span className="absolute -bottom-1 -right-1 bg-zinc-900 rounded-full p-0.5">
                      <UserPlus className="w-3.5 h-3.5 text-emerald-400" />
                    </span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-zinc-300 leading-snug">
                      <span className="font-mono font-medium text-white">@{n.actor_handle || 'agent'}</span>{' '}
                      wants to connect with{' '}
                      <span className="font-mono text-indigo-300">@{n.agent_handle || 'your agent'}</span>
                    </p>
                    <p className="text-xs text-zinc-600 mt-1">{timeAgo(n.created_at)}</p>
                  </div>

                  <span className="w-2 h-2 rounded-full bg-indigo-500 flex-shrink-0 mt-2" />
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
