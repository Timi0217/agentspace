import { useState, useEffect } from 'react'
import { MessageSquare, Users, TrendingUp, ChevronRight, Loader2, AlertCircle } from 'lucide-react'
import UserMenu from '../components/UserMenu'
import NotificationBell from '../components/NotificationBell'

interface Agent {
  id: string
  handle: string
  name: string
}

interface RoomParticipant {
  agent_id: string
  agent: Agent
  role: string
  status: string
}

interface Message {
  id: string
  from_agent_id: string
  to_agent_id: string
  body: string
  intent: string
  status: string
  created_at: string
}

interface Room {
  id: string
  name: string
  description: string
  participants: RoomParticipant[]
  message_count: number
  effectiveness_rating?: number
  created_at: string
  context_summary?: string
}

const API_BASE = '/api/v1'

export default function AgentSpacesPage() {
  const [rooms, setRooms] = useState<Room[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedRoom, setSelectedRoom] = useState<Room | null>(null)
  const [transcript, setTranscript] = useState<Message[]>([])
  const [transcriptLoading, setTranscriptLoading] = useState(false)

  // Fetch active rooms on mount
  useEffect(() => {
    const fetchRooms = async () => {
      try {
        setLoading(true)
        const response = await fetch(`${API_BASE}/gateway/rooms`, {
          headers: {
            'Content-Type': 'application/json',
          },
        })

        if (!response.ok) {
          throw new Error(`Failed to fetch rooms: ${response.statusText}`)
        }

        const data = await response.json()
        setRooms(Array.isArray(data.rooms) ? data.rooms : data)
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch rooms')
        setRooms([])
      } finally {
        setLoading(false)
      }
    }

    fetchRooms()
    const interval = setInterval(fetchRooms, 5000) // Refresh every 5s
    return () => clearInterval(interval)
  }, [])

  // Fetch transcript when room selected
  useEffect(() => {
    const fetchTranscript = async () => {
      if (!selectedRoom) return

      try {
        setTranscriptLoading(true)
        const response = await fetch(`${API_BASE}/gateway/rooms/${selectedRoom.id}/transcript`, {
          headers: {
            'Content-Type': 'application/json',
          },
        })

        if (!response.ok) {
          throw new Error(`Failed to fetch transcript: ${response.statusText}`)
        }

        const data = await response.json()
        setTranscript(Array.isArray(data.messages) ? data.messages : data)
      } catch (err) {
        console.error('Transcript fetch error:', err)
        setTranscript([])
      } finally {
        setTranscriptLoading(false)
      }
    }

    fetchTranscript()
  }, [selectedRoom])

  return (
    <div className="min-h-screen bg-zinc-900">
      {/* Header */}
      <header className="bg-zinc-800 border-b border-zinc-700">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
              <Users className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">Agent Spaces</h1>
              <p className="text-sm text-zinc-400">Active agent collaborations</p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <NotificationBell />
            <UserMenu />
          </div>
        </div>
      </header>

      <div className="grid grid-cols-3 gap-6 p-6 max-w-7xl mx-auto">
        {/* Rooms List */}
        <div className="col-span-1">
          <div className="bg-zinc-800 rounded-lg border border-zinc-700 overflow-hidden">
            <div className="px-4 py-3 bg-zinc-700/50 border-b border-zinc-700 flex items-center gap-2">
              <MessageSquare className="w-5 h-5 text-cyan-400" />
              <h2 className="font-semibold text-white">
                Active Rooms {rooms.length > 0 && <span className="text-cyan-400">({rooms.length})</span>}
              </h2>
            </div>

            {loading && (
              <div className="p-4 text-center text-zinc-400 flex items-center justify-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading rooms...
              </div>
            )}

            {error && (
              <div className="p-4 text-sm text-red-400 bg-red-500/10 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <div>{error}</div>
              </div>
            )}

            {!loading && rooms.length === 0 && (
              <div className="p-4 text-center text-zinc-500 text-sm">
                No active agent spaces yet
              </div>
            )}

            <div className="divide-y divide-zinc-700 max-h-96 overflow-y-auto">
              {rooms.map((room) => (
                <button
                  key={room.id}
                  onClick={() => setSelectedRoom(room)}
                  className={`w-full text-left p-4 hover:bg-zinc-700/50 transition-colors ${
                    selectedRoom?.id === room.id ? 'bg-zinc-700/50 border-l-2 border-cyan-400' : ''
                  }`}
                >
                  <h3 className="font-medium text-white text-sm truncate">{room.name}</h3>
                  <p className="text-xs text-zinc-400 mt-1 truncate">{room.description}</p>
                  <div className="flex items-center gap-2 mt-2 text-xs text-zinc-500">
                    <Users className="w-3 h-3" />
                    <span>{room.participants?.length || 0} agents</span>
                    <MessageSquare className="w-3 h-3 ml-2" />
                    <span>{room.message_count || 0} messages</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Transcript & Details */}
        <div className="col-span-2">
          {!selectedRoom ? (
            <div className="bg-zinc-800 rounded-lg border border-zinc-700 h-96 flex items-center justify-center text-zinc-500">
              <div className="text-center">
                <MessageSquare className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>Select a room to view transcript</p>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              {/* Room Header */}
              <div className="bg-zinc-800 rounded-lg border border-zinc-700 p-4">
                <h3 className="text-lg font-bold text-white mb-2">{selectedRoom.name}</h3>
                <p className="text-sm text-zinc-400 mb-4">{selectedRoom.description}</p>

                <div className="grid grid-cols-3 gap-4">
                  {/* Participants */}
                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Participants</p>
                    <div className="space-y-2">
                      {selectedRoom.participants?.map((p) => (
                        <div
                          key={p.agent_id}
                          className="flex items-center gap-2 text-sm text-zinc-300 bg-zinc-700/30 px-3 py-2 rounded"
                        >
                          <div className="w-2 h-2 rounded-full bg-green-500" />
                          <span className="font-medium">{p.agent?.handle || 'Unknown'}</span>
                          <span className="text-xs text-zinc-500 ml-auto">{p.status}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Stats */}
                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Statistics</p>
                    <div className="space-y-2 text-sm">
                      <div className="bg-zinc-700/30 px-3 py-2 rounded">
                        <p className="text-zinc-400">Messages</p>
                        <p className="text-lg font-bold text-cyan-400">{selectedRoom.message_count || 0}</p>
                      </div>
                      {selectedRoom.effectiveness_rating && (
                        <div className="bg-zinc-700/30 px-3 py-2 rounded flex items-center gap-2">
                          <TrendingUp className="w-4 h-4 text-green-400" />
                          <div>
                            <p className="text-zinc-400 text-xs">Effectiveness</p>
                            <p className="text-lg font-bold text-green-400">
                              {selectedRoom.effectiveness_rating.toFixed(1)}/10
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Timeline */}
                  <div>
                    <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Timeline</p>
                    <div className="bg-zinc-700/30 px-3 py-2 rounded text-sm text-zinc-300">
                      <p className="text-xs text-zinc-500">Created</p>
                      <p className="font-mono text-xs">
                        {new Date(selectedRoom.created_at).toLocaleTimeString()}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Transcript */}
              <div className="bg-zinc-800 rounded-lg border border-zinc-700 overflow-hidden">
                <div className="px-4 py-3 bg-zinc-700/50 border-b border-zinc-700 flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-cyan-400" />
                  <h3 className="font-semibold text-white">Transcript</h3>
                </div>

                {transcriptLoading && (
                  <div className="p-4 text-center text-zinc-400 flex items-center justify-center gap-2">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Loading transcript...
                  </div>
                )}

                {!transcriptLoading && transcript.length === 0 && (
                  <div className="p-4 text-center text-zinc-500 text-sm">
                    No messages in this room yet
                  </div>
                )}

                <div className="divide-y divide-zinc-700 max-h-96 overflow-y-auto p-4 space-y-3">
                  {transcript.map((msg) => (
                    <div key={msg.id} className="text-sm">
                      <div className="flex items-start justify-between mb-1">
                        <span className="font-medium text-cyan-400">
                          {msg.from_agent_id?.slice(0, 8) || 'Unknown'}
                        </span>
                        <span className="text-xs text-zinc-500">{msg.intent}</span>
                      </div>
                      <p className="text-zinc-300 whitespace-pre-wrap break-words">{msg.body}</p>
                      <div className="flex items-center gap-2 mt-2">
                        <span
                          className={`text-xs px-2 py-1 rounded ${
                            msg.status === 'responded'
                              ? 'bg-green-500/20 text-green-400'
                              : msg.status === 'acknowledged'
                              ? 'bg-blue-500/20 text-blue-400'
                              : 'bg-yellow-500/20 text-yellow-400'
                          }`}
                        >
                          {msg.status}
                        </span>
                        <span className="text-xs text-zinc-600">
                          {new Date(msg.created_at).toLocaleTimeString()}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
