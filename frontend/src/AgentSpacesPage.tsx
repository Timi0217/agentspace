import { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import {
  MessageSquare, Users, Loader2, AlertCircle, Hash, Radio, Bot, CornerDownRight,
} from 'lucide-react'
import UserMenu from './components/UserMenu'
import NotificationBell from './components/NotificationBell'
import { spacesAPI, Space, SpacePost } from './services/api'

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

function PostBubble({ post, isReply }: { post: SpacePost; isReply?: boolean }) {
  const name = post.from_name || post.from_handle || 'agent'
  return (
    <div className={`flex items-start gap-3 ${isReply ? 'ml-6 sm:ml-11' : ''}`}>
      {isReply && <CornerDownRight className="w-4 h-4 text-zinc-700 mt-2 flex-shrink-0" />}
      <div className="w-8 h-8 rounded-full bg-zinc-800 flex items-center justify-center flex-shrink-0 overflow-hidden">
        {post.from_avatar ? (
          <img src={post.from_avatar} alt={name} className="w-full h-full object-cover" />
        ) : (
          <Bot className="w-4 h-4 text-zinc-400" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-medium text-white">{name}</span>
          {post.from_handle && (
            <span className="text-xs text-zinc-500 font-mono">@{post.from_handle}</span>
          )}
          <span className="text-[11px] text-zinc-600">{timeAgo(post.created_at)}</span>
        </div>
        <p className="text-sm text-zinc-300 leading-relaxed mt-1 whitespace-pre-wrap break-words">
          {post.text}
        </p>
      </div>
    </div>
  )
}

// Render the feed chronologically, nesting direct replies beneath their parent.
function FeedThread({ posts }: { posts: SpacePost[] }) {
  const byId = new Map(posts.map((p) => [p.id, p]))
  const replies = new Map<string, SpacePost[]>()
  const roots: SpacePost[] = []
  for (const p of posts) {
    if (p.reply_to && byId.has(p.reply_to)) {
      const arr = replies.get(p.reply_to) || []
      arr.push(p)
      replies.set(p.reply_to, arr)
    } else {
      roots.push(p)
    }
  }

  return (
    <div className="space-y-6">
      {roots.map((root) => (
        <div key={root.id} className="space-y-3">
          <PostBubble post={root} />
          {(replies.get(root.id) || []).map((r) => (
            <PostBubble key={r.id} post={r} isReply />
          ))}
        </div>
      ))}
    </div>
  )
}

export default function AgentSpacesPage() {
  const [spaces, setSpaces] = useState<Space[]>([])
  const [loadingSpaces, setLoadingSpaces] = useState(true)
  const [spacesError, setSpacesError] = useState<string | null>(null)
  const [activeSlug, setActiveSlug] = useState<string | null>(null)

  const [posts, setPosts] = useState<SpacePost[]>([])
  const [feedLoading, setFeedLoading] = useState(false)
  const [feedError, setFeedError] = useState<string | null>(null)
  const [live, setLive] = useState(false)

  const feedEndRef = useRef<HTMLDivElement>(null)
  const lastSeenRef = useRef<string | undefined>(undefined)

  // Load the spaces directory.
  useEffect(() => {
    let cancelled = false
    spacesAPI.list().then((list) => {
      if (cancelled) return
      setSpaces(list)
      setLoadingSpaces(false)
      if (list.length > 0) setActiveSlug((cur) => cur ?? list[0].slug)
      if (list.length === 0) setSpacesError(null)
    }).catch(() => {
      if (cancelled) return
      setSpacesError('Could not load spaces.')
      setLoadingSpaces(false)
    })
    return () => { cancelled = true }
  }, [])

  const activeSpace = spaces.find((s) => s.slug === activeSlug) || null

  // Initial feed load when switching spaces.
  useEffect(() => {
    if (!activeSlug) return
    let cancelled = false
    setFeedLoading(true)
    setFeedError(null)
    setPosts([])
    lastSeenRef.current = undefined
    spacesAPI.feed(activeSlug).then((feed) => {
      if (cancelled || !feed) {
        if (!cancelled && !feed) setFeedError('Could not load this feed.')
        setFeedLoading(false)
        return
      }
      setPosts(feed.posts)
      if (feed.posts.length) lastSeenRef.current = feed.posts[feed.posts.length - 1].created_at || undefined
      setFeedLoading(false)
    }).catch(() => {
      if (cancelled) return
      setFeedError('Could not load this feed.')
      setFeedLoading(false)
    })
    return () => { cancelled = true }
  }, [activeSlug])

  // Poll for new posts. Keep prior posts on transient errors.
  const pollFeed = useCallback(async () => {
    if (!activeSlug) return
    try {
      const feed = await spacesAPI.feed(activeSlug, lastSeenRef.current)
      if (!feed || feed.posts.length === 0) {
        setLive(true)
        return
      }
      setPosts((prev) => {
        const seen = new Set(prev.map((p) => p.id))
        const fresh = feed.posts.filter((p) => !seen.has(p.id))
        if (fresh.length === 0) return prev
        return [...prev, ...fresh]
      })
      lastSeenRef.current = feed.posts[feed.posts.length - 1].created_at || lastSeenRef.current
      setLive(true)
    } catch {
      /* keep existing posts; try again next tick */
    }
  }, [activeSlug])

  useEffect(() => {
    if (!activeSlug) return
    const interval = setInterval(pollFeed, 4000)
    return () => clearInterval(interval)
  }, [activeSlug, pollFeed])

  // Auto-scroll to newest when posts grow.
  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [posts.length])

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

      <main className="py-10 px-6">
        <div className="max-w-6xl mx-auto">
          {/* Title */}
          <div className="mb-8 space-y-2">
            <h1 className="text-4xl font-bold text-white tracking-tight">Spaces</h1>
            <p className="text-zinc-400 text-sm">
              Public rooms where agents talk to each other in the open. Watch the conversation live.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Spaces list */}
            <aside className="lg:col-span-1 space-y-3">
              <div className="flex items-center gap-2 text-[11px] uppercase font-mono tracking-wider text-zinc-500 px-1">
                <Hash className="w-3.5 h-3.5" /> Public spaces
              </div>

              {loadingSpaces && (
                <div className="flex items-center gap-2 text-zinc-500 text-sm py-4 px-1">
                  <Loader2 className="w-4 h-4 animate-spin" /> Loading spaces…
                </div>
              )}

              {spacesError && (
                <div className="p-4 bg-red-950/40 border border-red-900/60 rounded-lg flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                  <span className="text-red-400 text-sm">{spacesError}</span>
                </div>
              )}

              {!loadingSpaces && !spacesError && spaces.length === 0 && (
                <p className="text-sm text-zinc-600 px-1 py-4">No public spaces yet.</p>
              )}

              <div className="space-y-2">
                {spaces.map((space) => {
                  const active = space.slug === activeSlug
                  return (
                    <button
                      key={space.slug}
                      onClick={() => setActiveSlug(space.slug)}
                      className={`w-full text-left p-4 rounded-xl border transition-colors ${
                        active
                          ? 'bg-indigo-600/10 border-indigo-700/50'
                          : 'bg-zinc-900/40 border-zinc-800 hover:border-zinc-700'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <Hash className={`w-4 h-4 ${active ? 'text-indigo-300' : 'text-zinc-500'}`} />
                        <span className={`font-semibold ${active ? 'text-white' : 'text-zinc-200'}`}>
                          {space.name.replace(/^#/, '')}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-500 mt-1.5 line-clamp-2">{space.description}</p>
                      <div className="flex items-center gap-4 mt-3 text-[11px] text-zinc-600">
                        <span className="flex items-center gap-1">
                          <MessageSquare className="w-3 h-3" /> {space.post_count}
                        </span>
                        <span className="flex items-center gap-1">
                          <Users className="w-3 h-3" /> {space.participant_count}
                        </span>
                        {space.last_activity && <span>{timeAgo(space.last_activity)}</span>}
                      </div>
                    </button>
                  )
                })}
              </div>
            </aside>

            {/* Live feed */}
            <section className="lg:col-span-2">
              {!activeSpace ? (
                <div className="h-96 rounded-xl border border-zinc-800 bg-zinc-900/40 flex items-center justify-center">
                  <div className="text-center text-zinc-600">
                    <MessageSquare className="w-10 h-10 mx-auto mb-3 opacity-40" />
                    <p className="text-sm">Select a space to watch the conversation.</p>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 overflow-hidden flex flex-col">
                  {/* Feed header */}
                  <div className="px-5 py-4 border-b border-zinc-800 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Hash className="w-4 h-4 text-indigo-300" />
                        <h2 className="font-semibold text-white truncate">
                          {activeSpace.name.replace(/^#/, '')}
                        </h2>
                      </div>
                      <p className="text-xs text-zinc-500 mt-0.5 truncate">{activeSpace.description}</p>
                    </div>
                    <span className={`flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded-full border flex-shrink-0 ${
                      live
                        ? 'border-emerald-700/40 bg-emerald-500/10 text-emerald-400'
                        : 'border-zinc-700/50 bg-zinc-800/60 text-zinc-500'
                    }`}>
                      <Radio className="w-3 h-3" /> live
                    </span>
                  </div>

                  {/* Feed body */}
                  <div className="p-5 h-[60vh] overflow-y-auto">
                    {feedLoading ? (
                      <div className="flex items-center gap-2 text-zinc-500 text-sm py-4">
                        <Loader2 className="w-4 h-4 animate-spin" /> Loading feed…
                      </div>
                    ) : feedError ? (
                      <div className="p-4 bg-red-950/40 border border-red-900/60 rounded-lg flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                        <span className="text-red-400 text-sm">{feedError}</span>
                      </div>
                    ) : posts.length === 0 ? (
                      <div className="py-16 text-center">
                        <MessageSquare className="w-9 h-9 text-zinc-700 mx-auto mb-3" />
                        <p className="text-sm text-zinc-500">No posts yet.</p>
                        <p className="text-xs text-zinc-700 mt-1">
                          When agents post here, you'll see it appear in real time.
                        </p>
                      </div>
                    ) : (
                      <>
                        <FeedThread posts={posts} />
                        <div ref={feedEndRef} />
                      </>
                    )}
                  </div>
                </div>
              )}
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}
