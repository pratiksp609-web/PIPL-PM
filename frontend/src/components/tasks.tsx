import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Paperclip, Pencil, Plus, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useProjectOptions, useUserOptions } from '../lib/hooks'
import { date } from '../lib/format'
import {
  Alert, Badge, Empty, Field, Modal, Pagination, Progress, QueryState, Select, clean, errorMessage, opts, useConfirm, useDebounced, useForm, useToast,
} from './ui'
import { DocLink, UploadModal } from './documents'

export const TASK_STATUSES = ['todo', 'in_progress', 'blocked', 'under_review', 'completed'] as const
export const TASK_PRIORITIES = ['low', 'medium', 'high', 'critical'] as const

const invalidate = (qc: ReturnType<typeof useQueryClient>) =>
  ['tasks', 'task', 'project', 'dashboard', 'calendar'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))

export function TasksPanel({ projectId, editable = true, initialFilters = {}, openTaskId }: {
  projectId?: number; editable?: boolean; initialFilters?: Record<string, string | boolean>; openTaskId?: number | null
}) {
  const session = useSession()
  const users = useUserOptions()
  const projects = useProjectOptions()
  const qc = useQueryClient()
  const toast = useToast()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [page, setPage] = useState(1)
  const [f, setF] = useState<Record<string, any>>({ status: '', priority: '', assignee_id: '', project_id: '', mine: false, overdue: false, sort: 'due', ...initialFilters })
  const [form, setForm] = useState<any | null>(null)
  const [detail, setDetail] = useState<number | null>(openTaskId ?? null)
  useEffect(() => { if (openTaskId) setDetail(openTaskId) }, [openTaskId])
  const params = { ...f, project_id: projectId ?? f.project_id, q: dq, page, page_size: 25 }
  const list = useQuery({ queryKey: ['tasks', params], queryFn: () => api.get('/api/tasks', params) })
  const quick = useMutation({
    mutationFn: ({ id, body }: { id: number; body: any }) => api.patch(`/api/tasks/${id}`, body),
    onSuccess: () => { toast('Task updated'); invalidate(qc) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const set = (k: string, v: any) => { setF((s) => ({ ...s, [k]: v })); setPage(1) }
  const isManager = session.permissions.manage_projects
  return (
    <div className="card">
      <div className="filters">
        <Field label="Search" className="grow"><input className="input" placeholder="Task title or description" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        {!projectId && <Field label="Project"><Select value={f.project_id} onChange={(v) => set('project_id', v)} options={projects.data ?? []} placeholder="All" /></Field>}
        <Field label="Status"><Select value={f.status} onChange={(v) => set('status', v)} options={opts(TASK_STATUSES)} placeholder="All" /></Field>
        <Field label="Priority"><Select value={f.priority} onChange={(v) => set('priority', v)} options={opts(TASK_PRIORITIES)} placeholder="All" /></Field>
        <Field label="Assignee"><Select value={f.assignee_id} onChange={(v) => set('assignee_id', v)} options={users.data ?? []} placeholder="Anyone" disabled={f.mine} /></Field>
        <Field label="Sort"><Select value={f.sort} onChange={(v) => set('sort', v)} options={[
          { value: 'due', label: 'Due date' }, { value: 'priority', label: 'Priority' }, { value: 'status', label: 'Status' },
          { value: 'created', label: 'Newest' }, { value: 'title', label: 'Title' },
        ]} /></Field>
        <label className="checkbox"><input type="checkbox" checked={!!f.mine} onChange={(e) => set('mine', e.target.checked)} /> My tasks</label>
        <label className="checkbox"><input type="checkbox" checked={!!f.overdue} onChange={(e) => set('overdue', e.target.checked)} /> Overdue</label>
        {editable && <button className="btn primary" style={{ alignSelf: 'flex-end' }} onClick={() => setForm({})}><Plus size={15} /> New task</button>}
      </div>
      <QueryState q={list}>
        {list.data?.items.length === 0 ? <Empty title="No tasks match these filters" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Task</th>{!projectId && <th>Project</th>}<th>Assignee</th><th>Priority</th><th>Status</th><th style={{ minWidth: 140 }}>Progress</th><th>Due</th><th /></tr></thead>
            <tbody>{list.data?.items.map((t: any) => {
              const mineOrManager = isManager || t.assignee_id === session.user.id || t.created_by_id === session.user.id
              return (
                <tr key={t.id} className={t.is_overdue ? 'overdue' : t.status === 'completed' ? 'muted-row' : ''}>
                  <td><button className="link-btn" onClick={() => setDetail(t.id)} style={{ fontWeight: 600, textAlign: 'left' }}>{t.title}</button>
                    {t.description && <div className="small muted" style={{ maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.description}</div>}</td>
                  {!projectId && <td className="small">{t.project_id ? <Link to={`/projects/${t.project_id}?tab=tasks`}>{t.project}</Link> : <span className="muted">General</span>}</td>}
                  <td>{t.assignee_name ?? <span className="muted">Unassigned</span>}</td>
                  <td><Badge value={t.priority} /></td>
                  <td>{editable && mineOrManager ? (
                    <Select className="sm" value={t.status} aria-label="Status" onChange={(v) => quick.mutate({ id: t.id, body: { status: v } })} options={opts(TASK_STATUSES)} />
                  ) : <Badge value={t.status} />}</td>
                  <td><Progress value={t.progress} overdue={t.is_overdue} /></td>
                  <td className="nowrap">{date(t.due_date)}{t.is_overdue && <div><Badge text="Overdue" kind="danger" /></div>}</td>
                  <td className="actions">{editable && mineOrManager && <button className="btn xs ghost" aria-label="Edit task" onClick={() => setForm(t)}><Pencil size={14} /></button>}</td>
                </tr>
              )
            })}</tbody>
          </table></div>
        )}
        {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
      </QueryState>
      {form && <TaskForm task={form.id ? form : null} projectId={projectId} onClose={() => setForm(null)} />}
      {detail && <TaskDetail id={detail} editable={editable} onClose={() => setDetail(null)} onEdit={(t) => { setDetail(null); setForm(t) }} />}
    </div>
  )
}

export function TaskForm({ task, projectId, onClose }: { task: any | null; projectId?: number; onClose: () => void }) {
  const session = useSession()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const users = useUserOptions()
  const projects = useProjectOptions()
  const isManager = session.permissions.manage_projects
  // Team members may only change status, progress and description of tasks assigned to them.
  const limited = !!task && !isManager && task.created_by_id !== session.user.id
  const f = useForm({
    title: task?.title ?? '', description: task?.description ?? '', project_id: String(task?.project_id ?? projectId ?? ''),
    assignee_id: String(task?.assignee_id ?? (isManager ? '' : session.user.id)), priority: task?.priority ?? 'medium',
    status: task?.status ?? 'todo', progress: task?.progress ?? 0, start_date: task?.start_date ?? '', due_date: task?.due_date ?? '',
  })
  const v = f.values
  const dateErr = v.start_date && v.due_date && v.due_date < v.start_date ? 'Due date cannot be before the start date' : undefined
  const save = () => f.submit(async () => {
    const full = clean({ ...v, project_id: Number(v.project_id) || null, assignee_id: Number(v.assignee_id) || null, progress: Number(v.progress) })
    const body = limited ? { status: v.status, progress: Number(v.progress), description: v.description || null } : full
    if (task) await api.patch(`/api/tasks/${task.id}`, body)
    else await api.post('/api/tasks', body)
    toast(task ? 'Task updated' : 'Task created')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  const remove = async () => {
    if (!(await confirm({ title: 'Delete task?', message: `"${task.title}" will be removed from lists. The audit trail is kept.`, danger: true, confirmText: 'Delete' }))) return
    try {
      await api.del(`/api/tasks/${task.id}`)
      toast('Task deleted')
      invalidate(qc)
      onClose()
    } catch (e) { toast(errorMessage(e), 'error') }
  }
  const assignable = isManager ? users.data ?? [] : (users.data ?? []).filter((u) => u.value === session.user.id)
  return (
    <Modal title={task ? 'Edit task' : 'New task'} onClose={onClose} size="lg"
      footer={<>
        {task && (isManager || task.created_by_id === session.user.id) && <button className="btn danger" style={{ marginRight: 'auto' }} onClick={remove}><Trash2 size={14} /> Delete</button>}
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={f.submitting || !v.title.trim() || !!dateErr} onClick={save}>{f.submitting ? 'Saving…' : 'Save task'}</button>
      </>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        {limited && <Alert kind="info">You can update the status, progress and notes of tasks assigned to you.</Alert>}
        <div className="form-grid">
          <Field label="Title" required error={f.errors.title} className="span-2"><input className="input" value={v.title} disabled={limited} onChange={(e) => f.set('title', e.target.value)} /></Field>
          <Field label="Project"><Select value={v.project_id} onChange={(x) => f.set('project_id', x)} options={projects.data ?? []} placeholder="General (no project)" disabled={limited || !!projectId} /></Field>
          <Field label="Assignee" error={f.errors.assignee_id}><Select value={v.assignee_id} onChange={(x) => f.set('assignee_id', x)} options={assignable} placeholder="Unassigned" disabled={limited} /></Field>
          <Field label="Priority"><Select value={v.priority} onChange={(x) => f.set('priority', x)} options={opts(TASK_PRIORITIES)} disabled={limited} /></Field>
          <Field label="Status"><Select value={v.status} onChange={(x) => { f.set('status', x); if (x === 'completed') f.set('progress', 100) }} options={opts(TASK_STATUSES)} /></Field>
          <Field label={`Progress: ${v.progress}%`} hint="Completed tasks are always 100%"><input type="range" min={0} max={100} step={5} value={v.progress} disabled={v.status === 'completed'} onChange={(e) => f.set('progress', Number(e.target.value))} /></Field>
          <div />
          <Field label="Start date"><input type="date" className="input" value={v.start_date} disabled={limited} onChange={(e) => f.set('start_date', e.target.value)} /></Field>
          <Field label="Due date" error={dateErr ?? f.errors.due_date}><input type="date" className="input" value={v.due_date} disabled={limited} onChange={(e) => f.set('due_date', e.target.value)} /></Field>
          <Field label="Description" className="span-2"><textarea className="input" value={v.description} onChange={(e) => f.set('description', e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  )
}

function TaskDetail({ id, editable, onClose, onEdit }: { id: number; editable: boolean; onClose: () => void; onEdit: (t: any) => void }) {
  const session = useSession()
  const qc = useQueryClient()
  const [upload, setUpload] = useState(false)
  const q = useQuery({ queryKey: ['task', id], queryFn: () => api.get(`/api/tasks/${id}`) })
  const t = q.data?.task
  const canEdit = editable && t && (session.permissions.manage_projects || t.assignee_id === session.user.id || t.created_by_id === session.user.id)
  return (
    <Modal title={t?.title ?? 'Task'} onClose={onClose} size="lg"
      footer={<>{canEdit && t.project_id && <button className="btn" onClick={() => setUpload(true)}><Paperclip size={14} /> Attach file</button>}
        {canEdit && <button className="btn primary" onClick={() => onEdit(t)}><Pencil size={14} /> Edit</button>}
        <button className="btn" onClick={onClose}>Close</button></>}>
      <QueryState q={q}>
        {t && <div className="stack">
          <div className="row"><Badge value={t.status} /><Badge value={t.priority} />{t.is_overdue && <Badge text="Overdue" kind="danger" />}</div>
          <Progress value={t.progress} overdue={t.is_overdue} />
          <dl className="dl">
            <dt>Project</dt><dd>{t.project_id ? <Link to={`/projects/${t.project_id}?tab=tasks`} onClick={onClose}>{t.project}</Link> : 'General'}</dd>
            <dt>Assignee</dt><dd>{t.assignee_name ?? 'Unassigned'}</dd>
            <dt>Start / due</dt><dd>{date(t.start_date)} → {date(t.due_date)}</dd>
            {t.completed_at && <><dt>Completed</dt><dd>{date(t.completed_at)}</dd></>}
            <dt>Description</dt><dd className="pre">{t.description || '—'}</dd>
          </dl>
          <div>
            <div className="section-title">Attachments</div>
            {q.data.attachments.length === 0 ? <p className="small muted">No attachments.</p> : (
              <ul className="list-plain">{q.data.attachments.map((d: any) => <li key={d.id}><DocLink doc={{ ...d, original_filename: d.title }} /></li>)}</ul>
            )}
          </div>
        </div>}
      </QueryState>
      {upload && t && <UploadModal projectId={t.project_id} category="other" links={{ task_id: t.id }} title={`Attach file to task`}
        onClose={() => setUpload(false)} onUploaded={() => qc.invalidateQueries({ queryKey: ['task', id] })} />}
    </Modal>
  )
}
