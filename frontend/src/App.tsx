import { lazy } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './lib/auth'
import { Spinner } from './components/ui'
import Layout from './components/Layout'
import Login from './pages/Login'
const Dashboard = lazy(() => import('./pages/Dashboard'))
const CalendarPage = lazy(() => import('./pages/Calendar'))
const Projects = lazy(() => import('./pages/Projects'))
const ProjectWorkspace = lazy(() => import('./pages/ProjectWorkspace'))
const Clients = lazy(() => import('./pages/Clients'))
const ClientProfile = lazy(() => import('./pages/ClientProfile'))
const TasksPage = lazy(() => import('./pages/Tasks'))
const PaymentsPage = lazy(() => import('./pages/Payments'))
const ProcurementPage = lazy(() => import('./pages/Procurement'))
const UpdatesPage = lazy(() => import('./pages/Updates'))
const ReportsPage = lazy(() => import('./pages/Reports'))
const DocumentsPage = lazy(() => import('./pages/Documents'))
const NotificationsPage = lazy(() => import('./pages/Notifications'))
const SettingsPage = lazy(() => import('./pages/Settings'))

function Protected({ children, finance }: { children: React.ReactNode; finance?: boolean }) {
  const { session, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Spinner block />
  if (!session) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />
  if (finance && !session.permissions.finance) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Dashboard />} />
        <Route path="calendar" element={<CalendarPage />} />
        <Route path="projects" element={<Projects />} />
        <Route path="projects/:id" element={<ProjectWorkspace />} />
        <Route path="clients" element={<Clients />} />
        <Route path="clients/:id" element={<ClientProfile />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="payments" element={<Protected finance><PaymentsPage /></Protected>} />
        <Route path="procurement" element={<ProcurementPage />} />
        <Route path="updates" element={<UpdatesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<div className="empty"><h3>Page not found</h3><p>The page you requested does not exist.</p></div>} />
      </Route>
    </Routes>
  )
}
