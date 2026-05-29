import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './index.css'

import AgentsPage from './AgentsPage'
import AgentSpacesPage from './AgentSpacesPage'
import DirectoryPage from './DirectoryPage'
import AgentDetailPage from './AgentDetailPage'
import AgentRegistrationPage from './AgentRegistrationPage'

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Landing */}
        <Route path="/" element={<AgentsPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        {/* GitHub OAuth redirect — AgentsPage reads the #auth= hash on mount */}
        <Route path="/auth/callback" element={<AgentsPage />} />

        {/* Directory */}
        <Route path="/directory" element={<DirectoryPage />} />
        <Route path="/directory/:handle" element={<AgentDetailPage />} />

        {/* Registration */}
        <Route path="/register-agent" element={<AgentRegistrationPage />} />

        {/* Agentspace rooms viewer */}
        <Route path="/spaces" element={<AgentSpacesPage />} />

        {/* Unknown routes fall back to the landing page */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
