import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, FolderKanban, Pencil, Plus } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useClientOptions, useUserOptions } from '../lib/hooks'
import { CURRENCIES, date, label, money } from '../lib/format'
import {
  Alert, Badge, Empty, Field, Modal, Pagination, Progress, QueryState, Select, clean, errorMessage, opts, useConfirm, useDebounced,
  useForm, useToast,
} from '../components/ui'
import { PageHead } from '../components/Layout'

export const PROJECT_STATUSES = ['planning', 'active', 'on_hold', 'completed', 'cancelled'] as const
export const PRIORITIES = ['low', 'medium', 'high', 'critical'] as const

export default function Projects() {
  const session = useSession()
  const [sp, setSp] = useSearchParams()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<any | null>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const clients = useClientOptions()
  const users = useUserOptions()
  const filters = {
    q: dq, status: sp.get('status') ?? '', client_id: sp.get('client_id') ?? '', manager_id: sp.get('manager_id') ?? '',
    priority: sp.get('priority') ?? '', overdue: sp.get('overdue') === '1', archived_only: sp.get('archived') === '1',
    sort: sp.get('sort') ?? '-updated_at', page, page_size: 20,
  }
  const setFilter = (k: string, v: string) => {
    const n = new URLSearchParams(sp)
    if (v) n.set(k, v)
    else n.delete(k)
    setSp(n, { replace: true })
    setPage(1)
  }
  const list = useQuery({ queryKey: ['projects', filters], queryFn: () => api.get('/api/projects', filters) })
  const archive = useMutation({
    mutationFn: ({ id, archived }: { id: number; archived: boolean }) => api.post(`/api/projects/${id}/archive`, {}, { archived }),
    onSuccess: (_, v) => { toast(v.archived ? 'Project archived' : 'Project restored'); qc.invalidateQueries({ queryKey: ['projects'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const canManage = session.permissions.manage_projects

  return (
    <>
      <PageHead title="Projects" sub="All projects with their unique project ID, client, schedule and progress."
        actions={canManage && <button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> New project</button>} />
      <div className="card">
        <div className="filters">
          <Field label="Search" className="grow"><input className="input" placeholder="Name, project ID, client…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
          <Field label="Status"><Select value={filters.status} onChange={(v) => setFilter('status', v)} options={opts(PROJECT_STATUSES)} placeholder="All" /></Field>
          <Field label="Client"><Select value={filters.client_id} onChange={(v) => setFilter('client_id', v)} options={clients.data ?? []} placeholder="All" /></Field>
          <Field label="Manager"><Select value={filters.manager_id} onChange={(v) => setFilter('manager_id', v)} options={(users.data ?? []).filter((u) => u.role !== 'team_member')} placeholder="All" /></Field>
          <Field label="Priority"><Select value={filters.priority} onChange={(v) => setFilter('priority', v)} options={opts(PRIORITIES)} placeholder="All" /></Field>
          <Field label="Sort"><Select value={filters.sort} onChange={(v) => setFilter('sort', v)} options={[
            { value: '-updated_at', label: 'Recently updated' }, { value: 'due', label: 'Due date (soonest)' }, { value: 'code', label: 'Project ID' },
            { value: 'name', label: 'Name' }, { value: '-progress', label: 'Progress (high → low)' }, { value: 'progress', label: 'Progress (low → high)' },
          ]} /></Field>
          <label className="checkbox"><input type="checkbox" checked={filters.overdue} onChange={(e) => setFilter('overdue', e.target.checked ? '1' : '')} /> Overdue only</label>
          <label className="checkbox"><input type="checkbox" checked={filters.archived_only} onChange={(e) => setFilter('archived', e.target.checked ? '1' : '')} /> Archived</label>
        </div>
        <QueryState q={list}>
          {list.data?.items.length === 0 ? (
            <Empty icon={<FolderKanban size={36} />} title="No projects found" text={dq || sp.toString() ? 'Try changing the filters.' : 'Create your first project to get started.'}
              action={canManage && !sp.toString() && <button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> New project</button>} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Project</th><th>Client</th><th>Manager</th><th>Status</th><th>Priority</th><th>Progress</th><th>Due</th><th>Tasks</th>{session.permissions.finance && <th className="num">Contract value</th>}<th /></tr></thead>
                <tbody>
                  {list.data?.items.map((p: any) => (
                    <tr key={p.id} className={`clickable ${p.is_overdue ? 'overdue' : ''}`} onClick={() => nav(`/projects/${p.id}`)}>
                      <td><Link to={`/projects/${p.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }}>{p.name}</Link><div className="mono muted">{p.code}</div></td>
                      <td>{p.client_name}</td>
                      <td>{p.manager_name ?? '—'}</td>
                      <td><Badge value={p.status} />{p.archived_at && <> <Badge text="Archived" /></>}</td>
                      <td><Badge value={p.priority} /></td>
                      <td style={{ minWidth: 140 }}><Progress value={p.progress} overdue={p.is_overdue} /></td>
                      <td className="nowrap">{date(p.expected_completion_date)}{p.is_overdue && <div><Badge text="Overdue" kind="danger" /></div>}</td>
                      <td className="nowrap">{p.open_tasks ?? 0} open{p.overdue_tasks ? <div className="small" style={{ color: 'var(--danger)' }}>{p.overdue_tasks} overdue</div> : null}</td>
                      {session.permissions.finance && <td className="num">{money(p.contract_value, p.currency)}</td>}
                      <td className="actions" onClick={(e) => e.stopPropagation()}>
                        {canManage && <>
                          <button className="btn xs ghost" onClick={() => setEditing(p)} aria-label="Edit"><Pencil size={14} /></button>
                          <button className="btn xs ghost" aria-label={p.archived_at ? 'Restore' : 'Archive'} onClick={async () => {
                            if (await confirm({ title: p.archived_at ? 'Restore project?' : 'Archive project?', message: p.archived_at ? `${p.code} will become active again.` : `${p.code} will be hidden from active lists. All records are kept and it can be restored.`, confirmText: p.archived_at ? 'Restore' : 'Archive', danger: !p.archived_at }))
                              archive.mutate({ id: p.id, archived: !p.archived_at })
                          }}>{p.archived_at ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>
                        </>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {list.data && <Pagination page={page} pageSize={20} total={list.data.total} onPage={setPage} />}
        </QueryState>
      </div>
      {editing && <ProjectForm project={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={(p) => { setEditing(null); if (!editing.id) nav(`/projects/${p.id}`) }} />}
    </>
  )
}

export function ProjectForm({ project, onClose, onSaved }: { project: any | null; onClose: () => void; onSaved: (p: any) => void }) {
  const clients = useClientOptions()
  const users = useUserOptions()
  const session = useSession()
  const qc = useQueryClient()
  const toast = useToast()
  const f = useForm({
    name: project?.name ?? '', client_id: project?.client_id ?? '', description: project?.description ?? '',
    manager_id: project?.manager_id ?? session.user.id, start_date: project?.start_date ?? '', expected_completion_date: project?.expected_completion_date ?? '',
    actual_completion_date: project?.actual_completion_date ?? '', budget: project?.budget ?? '', contract_value: project?.contract_value ?? '',
    currency: project?.currency ?? 'INR', status: project?.status ?? 'planning', progress: project?.progress ?? 0, priority: project?.priority ?? 'medium',
    member_ids: (project?.member_ids ?? []) as number[],
  })
  const v = f.values
  const localError =
    v.start_date && v.expected_completion_date && v.expected_completion_date < v.start_date ? 'Expected completion cannot be before start date'
      : v.progress < 0 || v.progress > 100 ? 'Progress must be between 0 and 100' : null
  const save = () => f.submit(async () => {
    const body = clean({ ...v, progress: Number(v.progress), client_id: Number(v.client_id) || null, manager_id: Number(v.manager_id) || null })
    const res = project ? await api.patch(`/api/projects/${project.id}`, body) : await api.post('/api/projects', body)
    toast(project ? 'Project updated' : `Project ${res.code} created`)
    qc.invalidateQueries({ queryKey: ['projects'] })
    qc.invalidateQueries({ queryKey: ['project'] })
    qc.invalidateQueries({ queryKey: ['project-options'] })
    onSaved(res)
  }).catch(() => {})
  const e = f.errors
  return (
    <Modal title={project ? `Edit ${project.code}` : 'New project'} onClose={onClose} size="lg"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !!localError || !v.name || !v.client_id} onClick={save}>{f.submitting ? 'Saving…' : project ? 'Save changes' : 'Create project'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        {localError && <Alert kind="warn">{localError}</Alert>}
        {!project && <Alert kind="info">A unique project ID (PIPL-YYYY-NNNN) is generated automatically.</Alert>}
        <div className="form-grid">
          <Field label="Project name" required error={e.name} className="span-2"><input className="input" value={v.name} onChange={(x) => f.set('name', x.target.value)} maxLength={200} /></Field>
          <Field label="Client" required error={e.client_id} hint={clients.data?.length === 0 ? 'Create a client first under Clients.' : undefined}>
            <Select value={v.client_id} onChange={(x) => f.set('client_id', x)} options={clients.data ?? []} placeholder="Select client" />
          </Field>
          <Field label="Project manager" error={e.manager_id}><Select value={v.manager_id} onChange={(x) => f.set('manager_id', x)} options={(users.data ?? []).filter((u) => u.role !== 'team_member')} placeholder="Unassigned" /></Field>
          <Field label="Description" className="span-2" error={e.description}><textarea className="input" value={v.description} onChange={(x) => f.set('description', x.target.value)} /></Field>
          <Field label="Start date" error={e.start_date}><input type="date" className="input" value={v.start_date} onChange={(x) => f.set('start_date', x.target.value)} /></Field>
          <Field label="Expected completion" error={e.expected_completion_date}><input type="date" className="input" value={v.expected_completion_date} min={v.start_date || undefined} onChange={(x) => f.set('expected_completion_date', x.target.value)} /></Field>
          <Field label="Status" error={e.status}><Select value={v.status} onChange={(x) => f.set('status', x)} options={opts(PROJECT_STATUSES)} /></Field>
          <Field label="Actual completion" error={e.actual_completion_date} hint="Set automatically when marked completed"><input type="date" className="input" value={v.actual_completion_date} onChange={(x) => f.set('actual_completion_date', x.target.value)} /></Field>
          <Field label="Progress %" error={e.progress}><input type="number" min={0} max={100} className="input" value={v.progress} onChange={(x) => f.set('progress', x.target.value === '' ? 0 : Number(x.target.value))} /></Field>
          <Field label="Priority" error={e.priority}><Select value={v.priority} onChange={(x) => f.set('priority', x)} options={opts(PRIORITIES)} /></Field>
          {session.permissions.finance && <>
            <Field label="Budget" error={e.budget}><input type="number" min={0} step="0.01" className="input" value={v.budget} onChange={(x) => f.set('budget', x.target.value)} /></Field>
            <Field label="Approved contract value" error={e.contract_value} hint="Used for X only until a client PO is verified or a quotation approved"><input type="number" min={0} step="0.01" className="input" value={v.contract_value} onChange={(x) => f.set('contract_value', x.target.value)} /></Field>
            <Field label="Currency" error={e.currency}><Select value={v.currency} onChange={(x) => f.set('currency', x)} options={CURRENCIES.map((c) => ({ value: c, label: c }))} /></Field>
          </>}
          <Field label="Team members" className="span-2" hint="Team members only see projects they belong to or have tasks on.">
            <div className="row" style={{ gap: 6 }}>
              {(users.data ?? []).map((u) => {
                const on = v.member_ids.includes(u.value)
                return (
                  <button type="button" key={u.value} className={`btn xs ${on ? 'primary' : ''}`} onClick={() => f.set('member_ids', on ? v.member_ids.filter((x) => x !== u.value) : [...v.member_ids, u.value])}>
                    {u.label} <span className="muted" style={{ color: on ? '#dbe7f6' : undefined }}>· {label(u.role)}</span>
                  </button>
                )
              })}
            </div>
          </Field>
        </div>
      </div>
    </Modal>
  )
}
