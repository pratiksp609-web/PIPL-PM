import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { History, Paperclip, Pencil, Plus } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useClientOptions, useProjectOptions, useUserOptions } from '../lib/hooks'
import { date, dateTime, label } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, Pagination, QueryState, Select, clean, opts, useDebounced, useForm, useToast } from './ui'
import { DocLink, UploadModal } from './documents'

export const HEALTH = ['on_track', 'at_risk', 'delayed', 'blocked'] as const
const TEXT_FIELDS: [string, string][] = [
  ['work_completed', 'Work completed'], ['work_in_progress', 'Work in progress'], ['blockers', 'Blockers / issues'], ['risks', 'Risks'],
  ['materials_required', 'Materials required'], ['next_steps', 'Next steps'], ['remarks', 'Remarks'],
]

const invalidate = (qc: ReturnType<typeof useQueryClient>) =>
  ['updates', 'update', 'project', 'projects', 'dashboard'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))

export function UpdatesFeed({ projectId, editable = true }: { projectId?: number; editable?: boolean }) {
  const projects = useProjectOptions()
  const clients = useClientOptions()
  const users = useUserOptions()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [page, setPage] = useState(1)
  const [f, setF] = useState({ project_id: '', client_id: '', author_id: '', health: '', date_from: '', date_to: '', order: 'desc' })
  const [form, setForm] = useState<any | null>(null)
  const [detail, setDetail] = useState<number | null>(null)
  const set = (k: string, v: string) => { setF((s) => ({ ...s, [k]: v })); setPage(1) }
  const params = { ...f, project_id: projectId ?? f.project_id, q: dq, page, page_size: 15 }
  const list = useQuery({ queryKey: ['updates', params], queryFn: () => api.get('/api/updates', params) })
  return (
    <div className="card">
      <div className="filters">
        <Field label="Search" className="grow"><input className="input" placeholder="Work, blockers, next steps…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        {!projectId && <>
          <Field label="Project"><Select value={f.project_id} onChange={(v) => set('project_id', v)} options={projects.data ?? []} placeholder="All" /></Field>
          <Field label="Client"><Select value={f.client_id} onChange={(v) => set('client_id', v)} options={clients.data ?? []} placeholder="All" /></Field>
        </>}
        <Field label="Author"><Select value={f.author_id} onChange={(v) => set('author_id', v)} options={users.data ?? []} placeholder="Anyone" /></Field>
        <Field label="Health"><Select value={f.health} onChange={(v) => set('health', v)} options={opts(HEALTH)} placeholder="All" /></Field>
        <Field label="From"><input type="date" className="input" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} /></Field>
        <Field label="To"><input type="date" className="input" value={f.date_to} onChange={(e) => set('date_to', e.target.value)} /></Field>
        <Field label="Order"><Select value={f.order} onChange={(v) => set('order', v)} options={[{ value: 'desc', label: 'Newest first' }, { value: 'asc', label: 'Oldest first' }]} /></Field>
        {editable && <button className="btn primary" style={{ alignSelf: 'flex-end' }} onClick={() => setForm({})}><Plus size={15} /> Post update</button>}
      </div>
      <QueryState q={list}>
        {list.data?.items.length === 0 ? <Empty title="No progress updates" text="Updates record work completed, blockers and next steps with a timestamp and author." /> : (
          <div className="card-body">{list.data?.items.map((u: any) => (
            <div key={u.id} className={`timeline-item ${u.health}`}>
              <div className="between">
                <div className="row" style={{ flexWrap: 'wrap' }}>
                  <b>{dateTime(u.update_at)}</b><span className="muted">by {u.author_name}</span><Badge value={u.health} /><span className="kv-chip">Progress <b>{u.progress}%</b></span>
                  {u.revision_count > 0 && <Badge text={`Edited ×${u.revision_count}`} kind="info" />}
                </div>
                <button className="btn xs" onClick={() => setDetail(u.id)}><History size={13} /> Details & history</button>
              </div>
              {!projectId && <div className="small"><Link to={`/projects/${u.project_id}?tab=updates`}>{u.project}</Link> · {u.client_name}</div>}
              <p className="pre mt-8" style={{ margin: '6px 0 0' }}>{u.work_completed}</p>
              {u.blockers && <p className="small" style={{ margin: '6px 0 0', color: 'var(--danger)' }}><b>Blockers:</b> {u.blockers}</p>}
              {u.next_steps && <p className="small muted" style={{ margin: '4px 0 0' }}><b>Next:</b> {u.next_steps}</p>}
            </div>
          ))}</div>
        )}
        {list.data && <Pagination page={page} pageSize={15} total={list.data.total} onPage={setPage} />}
      </QueryState>
      {form && <UpdateForm projectId={projectId} onClose={() => setForm(null)} />}
      {detail && <UpdateDetail id={detail} editable={editable} onClose={() => setDetail(null)} />}
    </div>
  )
}

function UpdateForm({ projectId, onClose }: { projectId?: number; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const projects = useProjectOptions()
  const [pid, setPid] = useState(projectId ? String(projectId) : '')
  const proj = useQuery({ queryKey: ['project', pid], queryFn: () => api.get(`/api/projects/${pid}`), enabled: !!pid })
  const f = useForm({
    health: 'on_track', work_completed: '', progress: '' as string | number, work_in_progress: '', blockers: '', risks: '', materials_required: '',
    next_steps: '', planned_completion_date: '', remarks: '', apply_progress_to_project: true,
  })
  const v = f.values
  const current = proj.data?.project?.progress
  const save = () => f.submit(async () => {
    await api.post('/api/updates', { ...clean(v), project_id: Number(pid), progress: Number(v.progress), update_at: new Date().toISOString() })
    toast('Progress update posted')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  const progressOk = v.progress !== '' && Number(v.progress) >= 0 && Number(v.progress) <= 100
  return (
    <Modal title="Post progress update" onClose={onClose} size="lg"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !pid || !v.work_completed.trim() || !progressOk} onClick={save}>{f.submitting ? 'Posting…' : 'Post update'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <p className="small muted">The current date, time and your name are recorded automatically.</p>
        <div className="form-grid">
          <Field label="Project" required className="span-2"><Select value={pid} onChange={setPid} options={projects.data ?? []} placeholder="Select project" disabled={!!projectId} /></Field>
          <Field label="Health"><Select value={v.health} onChange={(x) => f.set('health', x)} options={opts(HEALTH)} /></Field>
          <Field label="Progress %" required error={f.errors.progress} hint={current != null ? `Project currently at ${current}%` : undefined}>
            <input type="number" min={0} max={100} className="input" value={v.progress} onChange={(e) => f.set('progress', e.target.value)} /></Field>
          {TEXT_FIELDS.map(([k, l]) => (
            <Field key={k} label={l} required={k === 'work_completed'} error={f.errors[k]} className="span-2">
              <textarea className="input" style={{ minHeight: k === 'work_completed' ? 90 : 56 }} value={(v as any)[k]} onChange={(e) => f.set(k as any, e.target.value)} />
            </Field>
          ))}
          <Field label="Planned completion date"><input type="date" className="input" value={v.planned_completion_date} onChange={(e) => f.set('planned_completion_date', e.target.value)} /></Field>
          <label className="checkbox" style={{ alignSelf: 'end' }}><input type="checkbox" checked={v.apply_progress_to_project} onChange={(e) => f.set('apply_progress_to_project', e.target.checked)} /> Also set project progress to this value</label>
        </div>
      </div>
    </Modal>
  )
}

function UpdateDetail({ id, editable, onClose }: { id: number; editable: boolean; onClose: () => void }) {
  const session = useSession()
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [upload, setUpload] = useState(false)
  const q = useQuery({ queryKey: ['update', id], queryFn: () => api.get(`/api/updates/${id}`) })
  const u = q.data?.update
  const canEdit = editable && u && (session.permissions.manage_projects || u.author_id === session.user.id)
  return (
    <Modal title="Progress update" onClose={onClose} size="lg"
      footer={<>{canEdit && <button className="btn" onClick={() => setUpload(true)}><Paperclip size={14} /> Attach file</button>}
        {canEdit && <button className="btn primary" onClick={() => setEditing(true)}><Pencil size={14} /> Correct update</button>}
        <button className="btn" onClick={onClose}>Close</button></>}>
      <QueryState q={q}>
        {u && <div className="stack">
          <div className="row" style={{ flexWrap: 'wrap' }}><b>{dateTime(u.update_at)}</b><span className="muted">by {u.author_name}</span><Badge value={u.health} /><span className="kv-chip">Progress <b>{u.progress}%</b></span></div>
          <div className="small"><Link to={`/projects/${u.project_id}?tab=updates`} onClick={onClose}>{u.project}</Link></div>
          <dl className="dl">
            {TEXT_FIELDS.map(([k, l]) => <span key={k} style={{ display: 'contents' }}><dt>{l}</dt><dd className="pre">{u[k] || '—'}</dd></span>)}
            <dt>Planned completion</dt><dd>{date(u.planned_completion_date)}</dd>
          </dl>
          {q.data.attachments.length > 0 && <div><div className="section-title">Attachments</div>
            <ul className="list-plain">{q.data.attachments.map((d: any) => <li key={d.id}><DocLink doc={{ ...d, original_filename: d.title }} /></li>)}</ul></div>}
          <div>
            <div className="section-title">Revision history</div>
            {q.data.revisions.length === 0 ? <p className="small muted">Original version, never edited.</p> : (
              <div className="stack">{q.data.revisions.map((r: any) => (
                <details key={r.revision_number} className="card card-body">
                  <summary><b>Before revision {r.revision_number}</b> · edited by {r.edited_by} on {dateTime(r.edited_at)} · reason: <i>{r.reason}</i></summary>
                  <dl className="dl mt-8">{Object.entries(r.snapshot).map(([k, val]) => (
                    <span key={k} style={{ display: 'contents' }}><dt>{label(k)}</dt>
                      <dd className="pre">{String(val ?? '—')}{String(val ?? '') !== String(u[k] ?? '') && <> <Badge text="changed" kind="warn" /></>}</dd></span>
                  ))}</dl>
                </details>
              ))}</div>
            )}
          </div>
        </div>}
      </QueryState>
      {editing && u && <UpdateEditForm u={u} onClose={() => setEditing(false)} />}
      {upload && u && <UploadModal projectId={u.project_id} category="other" links={{ update_id: u.id }} title="Attach file to update"
        onClose={() => setUpload(false)} onUploaded={() => qc.invalidateQueries({ queryKey: ['update', id] })} />}
    </Modal>
  )
}

function UpdateEditForm({ u, onClose }: { u: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const initial: Record<string, any> = { health: u.health, progress: u.progress, planned_completion_date: u.planned_completion_date ?? '' }
  TEXT_FIELDS.forEach(([k]) => { initial[k] = u[k] ?? '' })
  const f = useForm<Record<string, any>>({ ...initial, reason: '' })
  const v = f.values
  const changed = Object.keys(initial).filter((k) => String(v[k] ?? '') !== String(initial[k] ?? ''))
  const save = () => f.submit(async () => {
    const body: Record<string, any> = { reason: v.reason }
    for (const k of changed) body[k] = k === 'progress' ? Number(v[k]) : v[k] === '' ? null : v[k]
    await api.patch(`/api/updates/${u.id}`, body)
    toast('Update corrected; previous version kept in history')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  return (
    <Modal title="Correct progress update" onClose={onClose} size="lg"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || changed.length === 0 || v.reason.trim().length < 3 || !String(v.work_completed).trim()} onClick={save}>{f.submitting ? 'Saving…' : 'Save correction'}</button></>}>
      <div className="form">
        <Alert kind="info">The original text is preserved as a revision. A reason is required.</Alert>
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <div className="form-grid">
          <Field label="Reason for correction" required className="span-2" error={f.errors.reason}><input className="input" value={v.reason} onChange={(e) => f.set('reason', e.target.value)} /></Field>
          <Field label="Health"><Select value={v.health} onChange={(x) => f.set('health', x)} options={opts(HEALTH)} /></Field>
          <Field label="Progress %"><input type="number" min={0} max={100} className="input" value={v.progress} onChange={(e) => f.set('progress', e.target.value)} /></Field>
          {TEXT_FIELDS.map(([k, l]) => (
            <Field key={k} label={l} className="span-2"><textarea className="input" style={{ minHeight: 56 }} value={v[k]} onChange={(e) => f.set(k, e.target.value)} /></Field>
          ))}
          <Field label="Planned completion date"><input type="date" className="input" value={v.planned_completion_date} onChange={(e) => f.set('planned_completion_date', e.target.value)} /></Field>
        </div>
        <p className="small muted">{changed.length ? `Changing: ${changed.map(label).join(', ')}` : 'No changes yet.'}</p>
      </div>
    </Modal>
  )
}
