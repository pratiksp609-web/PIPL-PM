import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CalendarClock, CheckCircle2, Clock, FolderKanban, ListTodo, Wallet, Activity, RotateCcw } from 'lucide-react'
import { api } from '../lib/api'
import { useClientOptions, useProjectOptions } from '../lib/hooks'
import { useSession } from '../lib/auth'
import { date, daysUntil, label, money, relative } from '../lib/format'
import { Badge, Empty, Field, QueryState, Select, Stat, opts } from '../components/ui'
import { PageHead } from '../components/Layout'
import { MonthlyPaymentsChart, OutstandingChart, ProgressChart, StatusChart } from '../components/charts'

const STATUSES = ['planning', 'active', 'on_hold', 'completed', 'cancelled'] as const

export default function Dashboard() {
  const session = useSession()
  const [f, setF] = useState({ date_from: '', date_to: '', client_id: '', project_id: '', status: '' })
  const clients = useClientOptions()
  const projects = useProjectOptions()
  const q = useQuery({ queryKey: ['dashboard', f], queryFn: () => api.get('/api/dashboard', f) })
  const d = q.data
  const set = (k: keyof typeof f, v: string) => setF((s) => ({ ...s, [k]: v }))
  const dirty = Object.values(f).some(Boolean)

  return (
    <>
      <PageHead title="Dashboard" sub={`Welcome back, ${session.user.full_name.replace(/\s*\[.*?\]/, '')}. All figures are calculated from live records.`} />
      <div className="card mb-16">
        <div className="filters" style={{ borderRadius: 'var(--radius)', borderBottom: 0 }}>
          <Field label="From"><input type="date" className="input" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} /></Field>
          <Field label="To"><input type="date" className="input" value={f.date_to} onChange={(e) => set('date_to', e.target.value)} /></Field>
          <Field label="Client"><Select value={f.client_id} onChange={(v) => set('client_id', v)} options={clients.data ?? []} placeholder="All clients" /></Field>
          <Field label="Project" className="grow"><Select value={f.project_id} onChange={(v) => set('project_id', v)} options={projects.data ?? []} placeholder="All projects" /></Field>
          <Field label="Status"><Select value={f.status} onChange={(v) => set('status', v)} options={opts(STATUSES)} placeholder="All statuses" /></Field>
          {dirty && <button className="btn ghost" onClick={() => setF({ date_from: '', date_to: '', client_id: '', project_id: '', status: '' })}><RotateCcw size={14} /> Reset</button>}
        </div>
      </div>

      <QueryState q={q}>
        {d && (
          <div className="stack">
            <div className="grid grid-4">
              <Link to="/projects" className="stat-link"><Stat icon={<FolderKanban size={14} />} label="Total projects" value={d.counts.total_projects} sub={`${d.counts.active_projects} active · ${d.counts.completed_projects} completed`} /></Link>
              <Link to="/projects?status=active" className="stat-link"><Stat icon={<Activity size={14} />} label="Active projects" value={d.counts.active_projects} tone="ok" /></Link>
              <Link to="/projects?overdue=1" className="stat-link"><Stat icon={<AlertTriangle size={14} />} label="Overdue projects" value={d.counts.overdue_projects} tone={d.counts.overdue_projects ? 'danger' : ''} sub="Past expected completion" /></Link>
              <Link to="/tasks?overdue=1" className="stat-link"><Stat icon={<ListTodo size={14} />} label="Pending tasks" value={d.counts.pending_tasks} tone={d.counts.overdue_tasks ? 'warn' : ''} sub={`${d.counts.overdue_tasks} overdue`} /></Link>
            </div>

            {d.finance_visible && (
              <div className="grid grid-4">
                {Object.keys(d.receivables).length === 0 && <Stat icon={<Wallet size={14} />} label="Outstanding receivables" value={money(0)} />}
                {Object.entries(d.receivables as Record<string, any>).map(([cur, r]) => (
                  <Link key={cur} to="/payments" className="stat-link">
                    <Stat icon={<Wallet size={14} />} label={`Outstanding receivables (${cur})`} value={money(r.outstanding, cur)}
                      sub={<>X {money(r.contract_value, cur, { compact: true })} − Y {money(r.verified_received, cur, { compact: true })}{Number(r.credit) > 0 && <> · credit {money(r.credit, cur)}</>}</>} />
                  </Link>
                ))}
                <Link to="/payments?status=pending,recorded" className="stat-link">
                  <Stat icon={<Clock size={14} />} label="Pending client payments" value={d.counts.pending_client_payments}
                    sub={`${d.pending_payments.recorded?.count ?? 0} awaiting verification · ${d.pending_payments.pending?.count ?? 0} expected`} />
                </Link>
                <Link to="/payments?overdue=1" className="stat-link">
                  <Stat icon={<AlertTriangle size={14} />} label="Overdue receivables" value={d.counts.overdue_receivables} tone={d.counts.overdue_receivables ? 'danger' : ''} sub="Expected payments past due date" />
                </Link>
              </div>
            )}

            <div className="grid grid-2">
              <div className="card">
                <div className="card-head"><div><h3>Project progress</h3><p>Actual progress vs linear plan estimate</p></div></div>
                <div className="card-body">
                  {d.charts.project_progress.length ? <ProgressChart data={d.charts.project_progress} /> : <Empty title="No projects" text="Projects matching the filters will appear here." />}
                </div>
              </div>
              <div className="card">
                <div className="card-head"><div><h3>Project status distribution</h3><p>{d.counts.total_projects} projects in scope</p></div></div>
                <div className="card-body">
                  {d.charts.status_distribution.length ? <StatusChart data={d.charts.status_distribution} /> : <Empty title="No projects" />}
                </div>
              </div>
            </div>

            {d.finance_visible && (
              <div className="grid grid-2">
                <div className="card">
                  <div className="card-head"><div><h3>Monthly verified payments</h3><p>Verified client receipts by month ({date(d.filters.date_from)} – {date(d.filters.date_to)})</p></div></div>
                  <div className="card-body">
                    {d.charts.payment_currencies.length ? <MonthlyPaymentsChart data={d.charts.monthly_payments} currencies={d.charts.payment_currencies} />
                      : <Empty title="No verified payments in this period" />}
                  </div>
                </div>
                <div className="card">
                  <div className="card-head"><div><h3>Outstanding balances by project</h3><p>Y received and Z outstanding against contract value X</p></div></div>
                  <div className="card-body">
                    {d.charts.outstanding_by_project.length ? <OutstandingChart data={d.charts.outstanding_by_project} /> : <Empty title="No contract values recorded yet" />}
                  </div>
                </div>
              </div>
            )}

            <div className="grid grid-3">
              <div className="card">
                <div className="card-head"><h3><CalendarClock size={16} style={{ verticalAlign: -3 }} /> Upcoming deadlines</h3><Link to="/calendar" className="small">Calendar</Link></div>
                {d.upcoming_deadlines.length === 0 ? <Empty title="Nothing due in the next 30 days" /> : (
                  <div className="feed">
                    {d.upcoming_deadlines.map((x: any) => {
                      const days = daysUntil(x.date)
                      return (
                        <div key={`${x.kind}-${x.id}`} className="feed-item">
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <Link to={x.kind === 'project' ? `/projects/${x.id}` : `/tasks?task=${x.id}`} style={{ fontWeight: 600 }}>{x.title}</Link>
                            <div className="when">{label(x.kind)} · {date(x.date)}</div>
                          </div>
                          <Badge text={days === 0 ? 'Today' : `${days} d`} kind={days !== null && days <= 3 ? 'warn' : 'info'} />
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
              <div className="card">
                <div className="card-head"><h3><AlertTriangle size={16} style={{ verticalAlign: -3 }} /> Overdue projects</h3></div>
                {d.overdue_projects.length === 0 ? <Empty title="No overdue projects" icon={<CheckCircle2 size={36} />} /> : (
                  <div className="feed">
                    {d.overdue_projects.map((p: any) => (
                      <div key={p.id} className="feed-item">
                        <div style={{ flex: 1 }}>
                          <Link to={`/projects/${p.id}`} style={{ fontWeight: 600 }}>{p.code} · {p.name}</Link>
                          <div className="when">Due {date(p.expected_completion_date)} · {p.progress}% complete</div>
                        </div>
                        <Badge text={`${p.days_overdue} d late`} kind="danger" />
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div className="card">
                <div className="card-head"><h3>Recent project updates</h3><Link to="/updates" className="small">All updates</Link></div>
                {d.recent_updates.length === 0 ? <Empty title="No updates in this period" /> : (
                  <div className="feed">
                    {d.recent_updates.map((u: any) => (
                      <div key={u.id} className="feed-item">
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="row between"><Link to={`/projects/${u.project_id}?tab=updates`} style={{ fontWeight: 600 }}>{u.project}</Link><Badge value={u.health} /></div>
                          <p className="small" style={{ margin: '4px 0' }}>{u.summary}</p>
                          <div className="when">{u.author} · {relative(u.update_at)} · {u.progress}%</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </QueryState>
    </>
  )
}
