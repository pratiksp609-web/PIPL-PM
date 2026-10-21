import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, FileDown, FileSpreadsheet, RefreshCw, Sparkles } from 'lucide-react'
import { api, downloadFile } from '../lib/api'
import { useSession } from '../lib/auth'
import { useClientOptions, useProjectOptions, useUserOptions } from '../lib/hooks'
import { date, dateTime, label, money } from '../lib/format'
import { Alert, Badge, Empty, Field, Pagination, Progress, QueryState, Seg, Select, Stat, errorMessage, opts, useToast } from './ui'

const PERIODS = ['weekly', 'monthly', 'quarterly', 'annual', 'custom'] as const
type Period = typeof PERIODS[number]

export function ReportGenerator({ projectId, onGenerated }: { projectId?: number; onGenerated: (r: any) => void }) {
  const session = useSession()
  const projects = useProjectOptions()
  const clients = useClientOptions()
  const users = useUserOptions()
  const toast = useToast()
  const qc = useQueryClient()
  const ai = useQuery({ queryKey: ['ai-status'], queryFn: () => api.get('/api/reports/ai-status'), staleTime: 60_000 })
  const [period, setPeriod] = useState<Period>('weekly')
  const [scope, setScope] = useState<'company' | 'project'>(projectId ? 'project' : 'company')
  const [f, setF] = useState({ project_id: projectId ? String(projectId) : '', start_date: '', end_date: '', client_id: '', manager_id: '', status: '', use_ai: true })
  const set = (k: string, v: any) => setF((s) => ({ ...s, [k]: v }))
  const gen = useMutation({
    mutationFn: () => api.post('/api/reports', {
      period_type: period, scope, use_ai: f.use_ai,
      project_id: scope === 'project' ? Number(f.project_id) : null,
      start_date: period === 'custom' ? f.start_date : null, end_date: period === 'custom' ? f.end_date : null,
      client_id: scope === 'company' ? Number(f.client_id) || null : null, manager_id: scope === 'company' ? Number(f.manager_id) || null : null,
      status: scope === 'company' ? f.status || null : null,
    }),
    onSuccess: (r) => { toast('Report generated'); qc.invalidateQueries({ queryKey: ['reports'] }); onGenerated(r) },
  })
  const customBad = period === 'custom' && (!f.start_date || !f.end_date || f.end_date < f.start_date)
  return (
    <div className="card">
      <div className="card-head"><div><h3>Generate status report</h3><p>Built from live project, task, update{session.permissions.finance ? ', payment and procurement' : ''} records.</p></div></div>
      <div className="card-body stack">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <Seg value={period} onChange={setPeriod} options={PERIODS.map((p) => ({ id: p, label: label(p) }))} />
          {!projectId && <Seg value={scope} onChange={setScope} options={[{ id: 'company', label: 'Company-wide' }, { id: 'project', label: 'Single project' }]} />}
        </div>
        <div className="form">
          {scope === 'project' && !projectId && <Field label="Project" className="grow"><Select value={f.project_id} onChange={(v) => set('project_id', v)} options={projects.data ?? []} placeholder="Select project" /></Field>}
          {scope === 'company' && <>
            <Field label="Client"><Select value={f.client_id} onChange={(v) => set('client_id', v)} options={clients.data ?? []} placeholder="All clients" /></Field>
            <Field label="Project manager"><Select value={f.manager_id} onChange={(v) => set('manager_id', v)} options={(users.data ?? []).filter((u) => u.role !== 'team_member')} placeholder="All" /></Field>
            <Field label="Project status"><Select value={f.status} onChange={(v) => set('status', v)} options={opts(['planning', 'active', 'on_hold', 'completed', 'cancelled'])} placeholder="All" /></Field>
          </>}
          {period === 'custom' && <>
            <Field label="Start date" required><input type="date" className="input" value={f.start_date} onChange={(e) => set('start_date', e.target.value)} /></Field>
            <Field label="End date" required error={f.end_date && f.start_date && f.end_date < f.start_date ? 'Before start date' : undefined}><input type="date" className="input" value={f.end_date} onChange={(e) => set('end_date', e.target.value)} /></Field>
          </>}
        </div>
        {ai.data && (ai.data.configured
          ? <label className="checkbox"><input type="checkbox" checked={f.use_ai} onChange={(e) => set('use_ai', e.target.checked)} /> <Sparkles size={14} /> Include AI analysis ({ai.data.model})</label>
          : <Alert kind="info">{ai.data.message}</Alert>)}
        {gen.error && <Alert kind="danger">{errorMessage(gen.error)}</Alert>}
        <div><button className="btn primary" disabled={gen.isPending || customBad || (scope === 'project' && !f.project_id)} onClick={() => gen.mutate()}>
          {gen.isPending ? 'Generating…' : 'Generate report'}</button></div>
      </div>
    </div>
  )
}

export function ReportList({ projectId, selected, onSelect }: { projectId?: number; selected?: number | null; onSelect: (id: number) => void }) {
  const [page, setPage] = useState(1)
  const [period, setPeriod] = useState('')
  const q = useQuery({ queryKey: ['reports', projectId, period, page], queryFn: () => api.get('/api/reports', { project_id: projectId, period_type: period, page, page_size: 10 }) })
  return (
    <div className="card">
      <div className="card-head"><div><h3>Saved reports</h3></div>
        <Select className="sm" value={period} onChange={(v) => { setPeriod(v); setPage(1) }} options={opts(PERIODS)} placeholder="All periods" aria-label="Filter period" /></div>
      <QueryState q={q}>
        {q.data?.items.length === 0 ? <Empty title="No reports yet" /> : (
          <div className="feed">{q.data?.items.map((r: any) => (
            <button key={r.id} className="feed-item" style={{ textAlign: 'left', background: selected === r.id ? 'var(--steel-50)' : 'transparent', border: 0, borderBottom: '1px solid var(--steel-100)', cursor: 'pointer', width: '100%' }} onClick={() => onSelect(r.id)}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600 }}>{r.title}</div>
                <div className="when">{dateTime(r.created_at)} · AI: {label(r.ai_status)}</div>
              </div>
            </button>
          ))}</div>
        )}
        {q.data && <Pagination page={page} pageSize={10} total={q.data.total} onPage={setPage} />}
      </QueryState>
    </div>
  )
}

const TAG = {
  fact: { text: 'Confirmed fact', bg: '#e3f4ec', fg: '#155c3d' },
  estimate: { text: 'Estimate', bg: '#fdf1df', fg: '#7a4a0c' },
  recommendation: { text: 'Recommendation', bg: '#e6eff9', fg: '#173f6e' },
  issue: { text: 'Data issue', bg: '#fde8e6', fg: '#7d241a' },
  risk: { text: 'Risk', bg: '#fde8e6', fg: '#7d241a' },
}
function Tagged({ kind, items }: { kind: keyof typeof TAG; items: string[] }) {
  const t = TAG[kind]
  if (!items?.length) return null
  return (
    <div className="mb-16">
      <span className="fact-tag" style={{ background: t.bg, color: t.fg }}>{t.text}s</span>
      <ul className="list-dots mt-8">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  )
}

export function ReportView({ id }: { id: number }) {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['report', id], queryFn: () => api.get(`/api/reports/${id}`) })
  const ai = useQuery({ queryKey: ['ai-status'], queryFn: () => api.get('/api/reports/ai-status'), staleTime: 60_000 })
  const rerun = useMutation({
    mutationFn: () => api.post(`/api/reports/${id}/ai`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['report', id] }); qc.invalidateQueries({ queryKey: ['reports'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const r = q.data
  const d = r?.data
  const a = r?.ai_analysis
  const exp = (format: 'pdf' | 'xlsx') => downloadFile(`/api/reports/${id}/export`, `pipl-report-${id}.${format}`, { format }).catch((e) => toast(errorMessage(e), 'error'))
  return (
    <QueryState q={q}>
      {r && <div className="card">
        <div className="card-head">
          <div><h3>{r.title}</h3><p>Generated {dateTime(r.created_at)} · data as of {date(d.period.as_of)}</p></div>
          <div className="row">
            <button className="btn sm" onClick={() => exp('pdf')}><FileDown size={14} /> PDF</button>
            <button className="btn sm" onClick={() => exp('xlsx')}><FileSpreadsheet size={14} /> Excel</button>
          </div>
        </div>
        <div className="report-section">
          <div className="grid grid-4">
            <Stat label="Projects in scope" value={d.summary.projects_in_scope} sub={`${d.summary.on_track} on track · ${d.summary.at_risk} at risk · ${d.summary.delayed} delayed`} />
            <Stat label="Tasks completed" value={d.summary.tasks_completed_in_period} sub={`${d.summary.overdue_tasks} overdue tasks`} tone={d.summary.overdue_tasks ? 'warn' : ''} />
            <Stat label="Updates submitted" value={d.summary.updates_in_period} sub={`${d.summary.projects_missing_updates} project(s) missing updates`} tone={d.summary.projects_missing_updates ? 'warn' : ''} />
            <Stat label="Data issues" value={d.summary.data_issues} sub={`${d.summary.overdue_projects} overdue project(s)`} tone={d.summary.data_issues ? 'danger' : ''} />
          </div>
        </div>
        <div className="report-section">
          <div className="section-title"><Bot size={14} style={{ verticalAlign: -2 }} /> Analysis</div>
          {r.ai_status === 'success' && a ? (
            <>
              <p><Badge value={a.overall_health} /> {a.summary}</p>
              <p className="small muted">AI-generated from the records in this report. Facts, estimates and recommendations are labelled separately; check figures against the tables below.</p>
              <Tagged kind="fact" items={a.confirmed_facts} />
              <Tagged kind="estimate" items={a.estimates} />
              <Tagged kind="risk" items={a.risks} />
              <Tagged kind="issue" items={a.data_issues} />
              <Tagged kind="recommendation" items={a.recommendations} />
            </>
          ) : (
            <>
              <Alert kind={r.ai_status === 'failed' ? 'warn' : 'info'}>
                {(r.ai_status === 'not_configured' || (r.ai_status === 'skipped' && !ai.data?.configured)) && 'AI analysis is unavailable because no AI provider is configured. Showing the deterministic, template-based summary.'}
                {r.ai_status === 'failed' && <>AI analysis failed ({r.ai_error}). Showing the deterministic, template-based summary.</>}
                {r.ai_status === 'skipped' && ai.data?.configured && 'AI analysis was not requested for this report. Showing the deterministic, template-based summary.'}
                {ai.data?.configured && <> <button className="btn xs" disabled={rerun.isPending} onClick={() => rerun.mutate()}><RefreshCw size={12} /> {rerun.isPending ? 'Running…' : 'Run AI analysis'}</button></>}
              </Alert>
              <span className="fact-tag mt-8" style={{ background: TAG.fact.bg, color: TAG.fact.fg, display: 'inline-block' }}>Confirmed facts (from records)</span>
              <ul className="list-dots mt-8">{d.template_summary.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
            </>
          )}
        </div>
        {d.financial && <div className="report-section">
          <div className="section-title">Receivables (X − Y = Z)</div>
          <div className="row" style={{ flexWrap: 'wrap' }}>{Object.entries(d.financial.totals_by_currency).map(([cur, v]: [string, any]) => (
            <span key={cur} className="kv-chip">{cur}: X <b>{money(v.contract_value, cur)}</b> − Y <b>{money(v.verified_received, cur)}</b> = Z <b>{money(v.outstanding, cur)}</b>{Number(v.credit) > 0 && <> · credit <b>{money(v.credit, cur)}</b></>}</span>
          ))}</div>
          <p className="small muted mt-8">{d.financial.note}</p>
        </div>}
        <div className="report-section">
          <div className="section-title">Projects</div>
          {d.projects.length === 0 ? <Empty title="No projects match this report's filters" /> : (
            <div className="stack">{d.projects.map((p: any) => {
              const note = a?.project_notes?.find((n: any) => n.code === p.code)
              return (
                <div key={p.id} className="card card-body">
                  <div className="between" style={{ flexWrap: 'wrap', gap: 8 }}>
                    <div><Link to={`/projects/${p.id}`} style={{ fontWeight: 700 }}>{p.code} · {p.name}</Link><div className="small muted">{p.client} · PM {p.manager ?? '—'} · due {date(p.expected_completion_date)}</div></div>
                    <div className="row"><Badge value={p.status} /><Badge value={p.health} />{p.is_overdue && <Badge text="Overdue" kind="danger" />}</div>
                  </div>
                  <div className="mt-8" style={{ maxWidth: 420 }}><Progress value={p.progress} plan={p.planned_progress} overdue={p.is_overdue} /></div>
                  {p.planned_progress != null && <p className="small muted" style={{ margin: '4px 0 0' }}><span className="fact-tag" style={{ background: TAG.estimate.bg, color: TAG.estimate.fg }}>Estimate</span> Planned {p.planned_progress}%: {p.planned_progress_note}</p>}
                  {note && <p className="small mt-8"><Badge value={note.health} /> {note.note} <span className="muted">(AI)</span></p>}
                  <div className="grid grid-3 mt-8">
                    <div><b className="small">Completed in period ({p.completed_tasks.length})</b><ul className="list-dots small">{p.completed_tasks.slice(0, 6).map((t: any, i: number) => <li key={i}>{t.title}</li>)}</ul></div>
                    <div><b className="small">Overdue ({p.overdue_tasks.length})</b><ul className="list-dots small">{p.overdue_tasks.slice(0, 6).map((t: any, i: number) => <li key={i}>{t.title} ({t.days_overdue} d, {t.assignee ?? 'unassigned'})</li>)}</ul></div>
                    <div><b className="small">Upcoming</b><ul className="list-dots small">{p.upcoming.slice(0, 6).map((t: any, i: number) => <li key={i}>{date(t.date)}: {t.title}</li>)}</ul></div>
                  </div>
                  {p.blockers.length > 0 && <div className="mt-8"><b className="small">Blockers & risks</b><ul className="list-dots small">{p.blockers.slice(0, 5).map((b: any, i: number) => <li key={i}>{b.date}: {b.text}</li>)}</ul></div>}
                  {p.receivable && <p className="small mt-8">Receivable: X {money(p.receivable.contract_value, p.receivable.currency)} − Y {money(p.receivable.verified_received, p.receivable.currency)} = <b>Z {money(p.receivable.outstanding, p.receivable.currency)}</b>
                    {p.procurement && <> · Procurement committed {money(p.procurement.committed_cost, p.receivable.currency)}, {p.procurement.late_deliveries.length} late deliveries</>}</p>}
                  {p.data_issues.length > 0 && <div className="mt-8">{p.data_issues.map((i: any, k: number) => <Badge key={k} text={i.text} kind="warn" />)}</div>}
                  {p.next_actions.length > 0 && <div className="mt-8"><span className="fact-tag" style={{ background: TAG.recommendation.bg, color: TAG.recommendation.fg }}>Next actions (rule-based)</span>
                    <ul className="list-dots small mt-8">{p.next_actions.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul></div>}
                </div>
              )
            })}</div>
          )}
        </div>
      </div>}
    </QueryState>
  )
}

export function ReportsPanel({ projectId }: { projectId?: number }) {
  const [selected, setSelected] = useState<number | null>(null)
  return (
    <div className="split">
      <div className="stack">
        <ReportGenerator projectId={projectId} onGenerated={(r) => setSelected(r.id)} />
        <ReportList projectId={projectId} selected={selected} onSelect={setSelected} />
      </div>
      {selected ? <ReportView id={selected} /> : <div className="card"><Empty title="Select or generate a report" text="Weekly, monthly, quarterly, annual and custom reports are saved here and can be exported to PDF or Excel." /></div>}
    </div>
  )
}
