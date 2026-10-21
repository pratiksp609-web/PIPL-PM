import { Suspense, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Bell, Building2, CalendarDays, ChevronsLeft, ChevronsRight, FileBarChart, FileText, FolderKanban,
  LayoutDashboard, ListChecks, LogOut, Menu, PackageSearch, Search, Settings, Wallet, Newspaper, KeyRound,
} from 'lucide-react'
import { api } from '../lib/api'
import { useAuth, useSession } from '../lib/auth'
import { ROLE_LABEL, initials } from '../lib/format'
import { Spinner, useDebounced } from './ui'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/calendar', label: 'Calendar', icon: CalendarDays },
  { to: '/projects', label: 'Projects', icon: FolderKanban },
  { to: '/clients', label: 'Clients', icon: Building2 },
  { to: '/tasks', label: 'To-Do List', icon: ListChecks },
  { to: '/payments', label: 'Payments', icon: Wallet, finance: true },
  { to: '/procurement', label: 'BOM Purchase Orders', icon: PackageSearch },
  { to: '/updates', label: 'Updates', icon: Newspaper },
  { to: '/reports', label: 'Status Reports', icon: FileBarChart },
  { to: '/documents', label: 'Documents', icon: FileText },
  { to: '/notifications', label: 'Notifications', icon: Bell, badge: true },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function readCollapsed(): boolean {
  try {
    return localStorage.getItem('pipl.sidebar') === 'collapsed'
  } catch {
    return false
  }
}

export default function Layout() {
  const session = useSession()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const unread = useQuery({
    queryKey: ['unread-count'],
    queryFn: () => api.get<{ count: number }>('/api/notifications/unread-count'),
    refetchInterval: 60_000,
  })

  useEffect(() => setMobileOpen(false), [location.pathname])
  useEffect(() => {
    try {
      localStorage.setItem('pipl.sidebar', collapsed ? 'collapsed' : 'open')
    } catch {
      /* storage unavailable */
    }
  }, [collapsed])

  const count = unread.data?.count ?? 0
  return (
    <div className="app">
      <aside className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`} aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark">
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden><path d="M9 25V7h8.5a5.5 5.5 0 0 1 0 11H13" stroke="#f0a43a" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <div className="brand-text"><strong>PIPL</strong><span>AI Project Management</span></div>
        </div>
        <nav>
          {NAV.filter((n) => !n.finance || session.permissions.finance).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`} title={collapsed ? n.label : undefined}>
              <n.icon size={18} />
              <span className="nav-label">{n.label}</span>
              {n.badge && count > 0 && <span className="nav-badge">{count > 99 ? '99+' : count}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button className="collapse-btn" onClick={() => setCollapsed((c) => !c)} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? <ChevronsRight size={18} /> : <ChevronsLeft size={18} />}
            <span className="nav-label">Collapse</span>
          </button>
        </div>
      </aside>
      <div className={`backdrop-mobile ${mobileOpen ? 'show' : ''}`} onClick={() => setMobileOpen(false)} />
      <div className={`main ${collapsed ? 'collapsed' : ''}`}>
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
          <GlobalSearch />
          <div className="topbar-right">
            <NavLink to="/notifications" className="icon-btn" aria-label={`Notifications (${count} unread)`}>
              <Bell size={19} />
              {count > 0 && <span className="dot">{count > 9 ? '9+' : count}</span>}
            </NavLink>
            <UserMenu />
          </div>
        </header>
        <main className="content">
          <Suspense fallback={<Spinner block />}><Outlet /></Suspense>
        </main>
      </div>
    </div>
  )
}

function UserMenu() {
  const { session, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  if (!session) return null
  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button className="user-chip" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <span className="avatar">{initials(session.user.full_name)}</span>
        <span className="meta"><div style={{ fontWeight: 600, fontSize: 13 }}>{session.user.full_name}</div><small>{ROLE_LABEL[session.user.role]}</small></span>
      </button>
      {open && (
        <div className="dropdown" role="menu">
          <button onClick={() => { setOpen(false); nav('/settings') }}><Settings size={16} /> Settings</button>
          <button onClick={() => { setOpen(false); nav('/settings?tab=security') }}><KeyRound size={16} /> Change password</button>
          <button onClick={async () => { await logout(); nav('/login') }}><LogOut size={16} /> Sign out</button>
        </div>
      )}
    </div>
  )
}

const GROUP_LABELS: Record<string, string> = {
  projects: 'Projects', clients: 'Clients', quotations: 'Quotations', purchase_orders: 'Purchase orders',
  documents: 'Documents', tasks: 'Tasks', updates: 'Updates',
}

function GlobalSearch() {
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const dq = useDebounced(q.trim(), 250)
  const nav = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  const res = useQuery({
    queryKey: ['search', dq],
    queryFn: () => api.get('/api/search', { q: dq }),
    enabled: dq.length >= 2,
  })
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  const flat: { title: string; subtitle?: string; link: string; group: string }[] = []
  if (res.data) for (const [g, items] of Object.entries(res.data.results as Record<string, any[]>)) for (const it of items) flat.push({ ...it, group: g })
  const go = (link: string) => {
    setOpen(false)
    setQ('')
    nav(link)
  }
  return (
    <div className="search-box" ref={ref}>
      <Search size={16} />
      <input
        value={q}
        placeholder="Search projects, clients, POs, documents, tasks…"
        aria-label="Global search"
        onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0) }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, flat.length - 1)) }
          if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
          if (e.key === 'Enter' && flat[active]) go(flat[active].link)
          if (e.key === 'Escape') setOpen(false)
        }}
      />
      {open && dq.length >= 2 && (
        <div className="search-results">
          {res.isLoading && <div className="muted" style={{ padding: 10 }}>Searching…</div>}
          {res.error && <div className="muted" style={{ padding: 10 }}>Search failed. Try again.</div>}
          {res.data && flat.length === 0 && <div className="muted" style={{ padding: 10 }}>No results for “{dq}”.</div>}
          {res.data && Object.entries(res.data.results as Record<string, any[]>).filter(([, v]) => v.length).map(([g, items]) => (
            <div key={g} className="search-group">
              <h4>{GROUP_LABELS[g] ?? g}</h4>
              {items.map((it) => {
                const idx = flat.findIndex((f) => f.link === it.link && f.title === it.title)
                return (
                  <a key={`${g}-${it.id}-${it.title}`} href={it.link} className={`search-hit ${idx === active ? 'active' : ''}`}
                    onClick={(e) => { e.preventDefault(); go(it.link) }}>
                    <span>{it.title}</span>
                    {it.subtitle && <small>{it.subtitle}</small>}
                  </a>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function PageHead({ title, sub, actions }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  )
}

