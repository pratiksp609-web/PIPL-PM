import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, ArrowLeft, Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { date, dateTime, money } from '../lib/format'
import { Alert, Badge, Progress, QueryState, Stat, Tabs, errorMessage, useConfirm, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'
import { ProjectForm } from './Projects'
import { ClientPOPanel, QuotationsPanel } from '../components/commercial'
import { ProjectPaymentsPanel, XYZCard } from '../components/payments'
import { ProjectProcurementPanel } from '../components/procurement'
import { DocumentsPanel } from '../components/documents'
import { TasksPanel } from '../components/tasks'
import { UpdatesFeed } from '../components/updates'
import { ReportsPanel } from '../components/reports'

const ALL_TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'quotation', label: 'Quotation', finance: true },
  { id: 'client-po', label: 'Client PO', finance: true },
  { id: 'payments', label: 'Payments', finance: true },
  { id: 'bom', label: 'BOM & Purchase' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'updates', label: 'Updates' },
  { id: 'documents', label: 'Documents' },
  { id: 'reports', label: 'Status Reports' },
] as const
type TabId = typeof ALL_TABS[number]['id']

export default function ProjectWorkspace() {
  const { id } = useParams()
  const pid = Number(id)
  const session = useSession()
  const [sp, setSp] = useSearchParams()
  const [editing, setEditing] = useState(false)
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const q = useQuery({ queryKey: ['project', pid], queryFn: () => api.get(`/api/projects/${pid}`), enabled: Number.isFinite(pid) })
  const tabs = ALL_TABS.filter((t) => !('finance' in t) || session.permissions.finance)
  const requested = sp.get('tab') as TabId | null
  const tab: TabId = tabs.some((t) => t.id === requested) ? requested! : 'overview'
  const setTab = (t: TabId) => setSp(t === 'overview' ? {} : { tab: t }, { replace: true })
  const archive = useMutation({
    mutationFn: (archived: boolean) => api.post(`/api/projects/${pid}/archive`, {}, { archived }),
    onSuccess: (_, archived) => { toast(archived ? 'Project archived' : 'Project restored'); ['project', 'projects', 'project-options', 'dashboard'].forEach((k) => qc.invalidateQueries({ queryKey: [k] })) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const d = q.data
  const p = d?.project
  const editable = session.permissions.manage_projects && !p?.archived_at
  return (
    <QueryState q={q}>
      {p && <>
        <Link to="/projects" className="small row" style={{ marginBottom: 8 }}><ArrowLeft size={14} /> Projects</Link>
        <PageHead title={p.name}
          sub={<><span className="mono">{p.code}</span> · <Link to={`/clients/${p.client_id}`}>{p.client_name}</Link> · PM {p.manager_name ?? '—'}</>}
          actions={session.permissions.manage_projects && <>
            {!p.archived_at && <button className="btn" onClick={() => setEditing(true)}><Pencil size={14} /> Edit</button>}
            <button className="btn" onClick={async () => {
              const toArchive = !p.archived_at
              if (await confirm({ title: toArchive ? 'Archive project?' : 'Restore project?', message: toArchive ? 'Archived projects become read-only and are hidden from active lists. All records are kept.' : 'The project becomes editable again.', confirmText: toArchive ? 'Archive' : 'Restore' })) archive.mutate(toArchive)
            }}>{p.archived_at ? <><ArchiveRestore size={14} /> Restore</> : <><Archive size={14} /> Archive</>}</button>
          </>} />
        <div className="row mb-16" style={{ flexWrap: 'wrap' }}>
          <Badge value={p.status} /><Badge value={p.priority} />
          {p.is_overdue && <Badge text="Overdue" kind="danger" />}
          {p.is_sample && <Badge text="Sample data" kind="info" />}
          {p.archived_at && <Badge text={`Archived ${date(p.archived_at)}`} />}
        </div>
        {p.archived_at && <div className="mb-16"><Alert kind="warn">This project is archived and read-only.</Alert></div>}
        <div className="card mb-16"><div style={{ padding: '0 18px', overflowX: 'auto' }}><Tabs tabs={tabs.map((t) => ({ id: t.id, label: t.label }))} value={tab} onChange={setTab} /></div></div>
        {tab === 'overview' && <Overview d={d} setTab={setTab} />}
        {tab === 'quotation' && <QuotationsPanel projectId={pid} editable={editable} />}
        {tab === 'client-po' && <ClientPOPanel projectId={pid} editable={editable} />}
        {tab === 'payments' && <ProjectPaymentsPanel projectId={pid} editable={editable} />}
        {tab === 'bom' && <ProjectProcurementPanel projectId={pid} currency={p.currency} editable={editable} />}
        {tab === 'tasks' && <TasksPanel projectId={pid} editable={!p.archived_at} />}
        {tab === 'updates' && <UpdatesFeed projectId={pid} editable={!p.archived_at} />}
        {tab === 'documents' && <DocumentsPanel projectId={pid} />}
        {tab === 'reports' && <ReportsPanel projectId={pid} />}
        {editing && <ProjectForm project={p} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); qc.invalidateQueries({ queryKey: ['project', pid] }) }} />}
      </>}
    </QueryState>
  )
}

function Overview({ d, setTab }: { d: any; setTab: (t: TabId) => void }) {
  const p = d.project
  const u = d.latest_update
  return (
    <div className="stack">
      <div className="grid grid-4">
        <div className="card stat"><div className="label">Progress</div><div className="mt-8"><Progress value={p.progress} plan={d.planned_progress} overdue={p.is_overdue} /></div>
          <div className="sub">{d.planned_progress != null ? `Planned ${d.planned_progress}% (linear estimate from dates)` : 'No schedule dates to estimate plan'}</div></div>
        <Stat label="Schedule" value={date(p.expected_completion_date)} sub={<>Start {date(p.start_date)}{p.actual_completion_date && <> · completed {date(p.actual_completion_date)}</>}</>} tone={p.is_overdue ? 'danger' : ''} />
        <Stat label="Open tasks" value={p.open_tasks ?? 0} sub={`${p.overdue_tasks ?? 0} overdue`} tone={p.overdue_tasks ? 'warn' : ''} />
        <Stat label="Last update" value={u ? `${d.days_since_update} d ago` : 'None'} sub={u ? `by ${u.author}` : 'No progress updates yet'} tone={!u || d.days_since_update > 3 ? 'warn' : ''} />
      </div>
      {d.receivable && <XYZCard r={d.receivable} />}
      <div className="grid grid-2">
        <div className="card">
          <div className="card-head"><div><h3>Project details</h3></div></div>
          <div className="card-body">
            <dl className="dl">
              <dt>Project ID</dt><dd className="mono">{p.code}</dd>
              <dt>Client</dt><dd><Link to={`/clients/${p.client_id}`}>{p.client_name}</Link></dd>
              <dt>Project manager</dt><dd>{p.manager_name ?? '—'}</dd>
              <dt>Currency</dt><dd>{p.currency}</dd>
              {p.budget != null && <><dt>Budget</dt><dd>{money(p.budget, p.currency)}</dd></>}
              {p.contract_value != null && <><dt>Contract value (manual)</dt><dd>{money(p.contract_value, p.currency)}</dd></>}
              <dt>Documents</dt><dd><button className="link-btn" onClick={() => setTab('documents')}>{d.doc_count} file(s)</button></dd>
              <dt>Description</dt><dd className="pre">{p.description || '—'}</dd>
            </dl>
          </div>
        </div>
        <div className="card">
          <div className="card-head"><div><h3>Latest progress update</h3></div><button className="btn sm" onClick={() => setTab('updates')}>All updates</button></div>
          {u ? <div className="card-body">
            <div className="row" style={{ flexWrap: 'wrap' }}><b>{dateTime(u.update_at)}</b><span className="muted">by {u.author}</span><Badge value={u.health} /><span className="kv-chip">Progress <b>{u.progress}%</b></span></div>
            <p className="pre">{u.work_completed}</p>
            {u.blockers && <p className="small" style={{ color: 'var(--danger)' }}><b>Blockers:</b> {u.blockers}</p>}
            {u.next_steps && <p className="small muted"><b>Next steps:</b> {u.next_steps}</p>}
          </div> : <div className="card-body"><Alert kind="warn">No progress updates have been recorded for this project.</Alert></div>}
        </div>
      </div>
      <div className="card">
        <div className="card-head"><div><h3>Upcoming tasks</h3></div><button className="btn sm" onClick={() => setTab('tasks')}>All tasks</button></div>
        {d.upcoming_tasks.length === 0 ? <div className="card-body muted small">No open tasks with due dates.</div> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Task</th><th>Assignee</th><th>Priority</th><th>Status</th><th>Due</th></tr></thead>
            <tbody>{d.upcoming_tasks.map((t: any) => (
              <tr key={t.id} className={t.overdue ? 'overdue' : ''}><td><Link to={`/tasks?task=${t.id}`}>{t.title}</Link></td><td>{t.assignee ?? '—'}</td>
                <td><Badge value={t.priority} /></td><td><Badge value={t.status} /></td><td>{date(t.due_date)}{t.overdue && <> <Badge text="Overdue" kind="danger" /></>}</td></tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {d.procurement && (
        <div className="card card-body">
          <div className="between"><div className="section-title" style={{ margin: 0 }}>Procurement</div><button className="btn sm" onClick={() => setTab('bom')}>Open BOM & purchase</button></div>
          <div className="row mt-8" style={{ flexWrap: 'wrap' }}>
            <span className="kv-chip">Estimated <b>{money(d.procurement.estimated_cost, p.currency)}</b></span>
            <span className="kv-chip">Committed <b>{money(d.procurement.committed_cost, p.currency)}</b></span>
            <span className="kv-chip">Paid to suppliers <b>{money(d.procurement.supplier_paid, p.currency)}</b></span>
            <span className="kv-chip">Pending items <b>{d.procurement.pending_procurement_count}</b></span>
            <span className="kv-chip">Late deliveries <b>{d.procurement.late_deliveries.length}</b></span>
          </div>
          <p className="small muted mt-8">Supplier costs are tracked separately and never reduce the client receivable.</p>
        </div>
      )}
    </div>
  )
}
