import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Plus, Play } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { ROLE_LABEL, dateTime, label } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, Pagination, QueryState, Select, Tabs, errorMessage, opts, useForm, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'

type Tab = 'profile' | 'reminders' | 'users' | 'system' | 'audit'
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const ROLES = ['admin', 'project_manager', 'team_member'] as const

export default function SettingsPage() {
  const session = useSession()
  const [tab, setTab] = useState<Tab>('profile')
  const tabs: { id: Tab; label: string }[] = [
    { id: 'profile', label: 'Profile & security' },
    { id: 'reminders', label: 'Reminders & notifications' },
    ...(session.permissions.admin ? [{ id: 'users' as Tab, label: 'Users & roles' }] : []),
    { id: 'system', label: session.permissions.admin ? 'System rules & integrations' : 'Integrations' },
    ...(session.permissions.manage_projects ? [{ id: 'audit' as Tab, label: 'Audit log' }] : []),
  ]
  return (
    <>
      <PageHead title="Settings" />
      <div className="card mb-16"><div style={{ padding: '0 18px', overflowX: 'auto' }}><Tabs tabs={tabs} value={tab} onChange={setTab} /></div></div>
      {tab === 'profile' && <Profile />}
      {tab === 'reminders' && <Reminders />}
      {tab === 'users' && <Users />}
      {tab === 'system' && <System />}
      {tab === 'audit' && <AuditLog />}
    </>
  )
}

function Profile() {
  const session = useSession()
  const toast = useToast()
  const f = useForm({ current_password: '', new_password: '', confirm: '' })
  const v = f.values
  const mismatch = v.confirm && v.new_password !== v.confirm ? 'Passwords do not match' : undefined
  const weak = v.new_password && !(v.new_password.length >= 8 && /[A-Za-z]/.test(v.new_password) && /\d/.test(v.new_password)) ? 'At least 8 characters with letters and numbers' : undefined
  const save = () => f.submit(async () => {
    await api.post('/api/auth/change-password', { current_password: v.current_password, new_password: v.new_password })
    toast('Password changed. Other sessions have been signed out.')
    f.setValues({ current_password: '', new_password: '', confirm: '' })
  }).catch(() => {})
  const u = session.user
  return (
    <div className="grid grid-2">
      <div className="card card-body">
        <div className="section-title">Your account</div>
        <dl className="dl">
          <dt>Name</dt><dd>{u.full_name}</dd>
          <dt>Username</dt><dd className="mono">{u.username}</dd>
          <dt>Email</dt><dd>{u.email}</dd>
          <dt>Role</dt><dd><Badge text={ROLE_LABEL[u.role]} kind="info" /></dd>
        </dl>
        <p className="small muted mt-8">Name, email and role are managed by an administrator.</p>
      </div>
      <div className="card card-body">
        <div className="section-title"><KeyRound size={14} style={{ verticalAlign: -2 }} /> Change password</div>
        <div className="form">
          {f.formError && <Alert kind="danger">{f.formError}</Alert>}
          <Field label="Current password" required><input type="password" autoComplete="current-password" className="input" value={v.current_password} onChange={(e) => f.set('current_password', e.target.value)} /></Field>
          <Field label="New password" required error={weak ?? f.errors.new_password}><input type="password" autoComplete="new-password" className="input" value={v.new_password} onChange={(e) => f.set('new_password', e.target.value)} /></Field>
          <Field label="Confirm new password" required error={mismatch}><input type="password" autoComplete="new-password" className="input" value={v.confirm} onChange={(e) => f.set('confirm', e.target.value)} /></Field>
          <div><button className="btn primary" disabled={f.submitting || !v.current_password || !v.new_password || !!mismatch || !!weak || v.new_password !== v.confirm} onClick={save}>{f.submitting ? 'Saving…' : 'Change password'}</button></div>
        </div>
      </div>
    </div>
  )
}

function Reminders() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['settings-me'], queryFn: () => api.get('/api/settings/me') })
  const f = useForm<Record<string, any>>({})
  useEffect(() => { if (q.data) f.setValues({ ...q.data }) }, [q.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const v = f.values
  const save = () => f.submit(async () => {
    const r = await api.put('/api/settings/me', {
      reminders_enabled: v.reminders_enabled, reminder_interval_minutes: Number(v.reminder_interval_minutes), work_start: v.work_start, work_end: v.work_end,
      work_days: v.work_days, timezone: v.timezone, notify_email: v.notify_email, disabled_notification_types: v.disabled_notification_types,
    })
    qc.setQueryData(['settings-me'], r)
    toast('Notification settings saved')
  }).catch(() => {})
  const hoursErr = v.work_start && v.work_end && v.work_start >= v.work_end ? 'End must be after start' : undefined
  const intervalErr = v.reminder_interval_minutes && (Number(v.reminder_interval_minutes) < 15 || Number(v.reminder_interval_minutes) > 1440) ? 'Between 15 minutes and 24 hours' : undefined
  const zones: string[] = (Intl as any).supportedValuesOf ? (Intl as any).supportedValuesOf('timeZone') : ['Asia/Kolkata', 'UTC']
  return (
    <QueryState q={q}>
      {v.work_days && <div className="grid grid-2">
        <div className="card card-body">
          <div className="section-title">Progress report reminders</div>
          <div className="form">
            {f.formError && <Alert kind="danger">{f.formError}</Alert>}
            <label className="checkbox"><input type="checkbox" checked={v.reminders_enabled} onChange={(e) => f.set('reminders_enabled', e.target.checked)} /> Remind me to update task progress during working hours</label>
            <Field label="Reminder interval" error={intervalErr} hint="Default is every 2 hours. Only sent if you have open tasks.">
              <Select value={String(v.reminder_interval_minutes)} onChange={(x) => f.set('reminder_interval_minutes', x)} options={[
                { value: '30', label: 'Every 30 minutes' }, { value: '60', label: 'Every hour' }, { value: '120', label: 'Every 2 hours' },
                { value: '180', label: 'Every 3 hours' }, { value: '240', label: 'Every 4 hours' }, { value: '480', label: 'Once per working day (8 h)' },
              ]} />
            </Field>
            <div className="form-grid">
              <Field label="Working hours start"><input type="time" className="input" value={v.work_start} onChange={(e) => f.set('work_start', e.target.value)} /></Field>
              <Field label="Working hours end" error={hoursErr}><input type="time" className="input" value={v.work_end} onChange={(e) => f.set('work_end', e.target.value)} /></Field>
            </div>
            <Field label="Working days" error={v.work_days.length === 0 ? 'Select at least one day' : undefined}>
              <div className="row" style={{ flexWrap: 'wrap' }}>{DAYS.map((d, i) => (
                <label key={d} className="checkbox"><input type="checkbox" checked={v.work_days.includes(i)}
                  onChange={(e) => f.set('work_days', e.target.checked ? [...v.work_days, i].sort() : v.work_days.filter((x: number) => x !== i))} /> {d}</label>
              ))}</div>
            </Field>
            <Field label="Time zone"><Select value={v.timezone} onChange={(x) => f.set('timezone', x)} options={zones.map((z) => ({ value: z, label: z }))} /></Field>
            {v.last_progress_reminder_at && <p className="small muted">Last reminder sent {dateTime(v.last_progress_reminder_at)}.</p>}
          </div>
        </div>
        <div className="card card-body">
          <div className="section-title">Notification preferences</div>
          <div className="form">
            <label className="checkbox"><input type="checkbox" checked={v.notify_email} onChange={(e) => f.set('notify_email', e.target.checked)} /> Also send notifications by email</label>
            {!v.email_configured && <Alert kind="warn">Email delivery is not configured on the server (SMTP settings missing). Notifications are shown in the app only.</Alert>}
            <div className="small muted">Notification types you receive:</div>
            <div className="list-plain">{Object.entries(v.notification_types as Record<string, string>).map(([k, l]) => (
              <label key={k} className="checkbox"><input type="checkbox" checked={!v.disabled_notification_types.includes(k)}
                onChange={(e) => f.set('disabled_notification_types', e.target.checked ? v.disabled_notification_types.filter((x: string) => x !== k) : [...v.disabled_notification_types, k])} /> {l}</label>
            ))}</div>
          </div>
        </div>
        <div><button className="btn primary" disabled={f.submitting || !!hoursErr || !!intervalErr || v.work_days.length === 0} onClick={save}>{f.submitting ? 'Saving…' : 'Save settings'}</button></div>
      </div>}
    </QueryState>
  )
}

function Users() {
  const qc = useQueryClient()
  const toast = useToast()
  const session = useSession()
  const [inactive, setInactive] = useState(false)
  const [form, setForm] = useState<any | null>(null)
  const q = useQuery({ queryKey: ['users-admin', inactive], queryFn: () => api.get('/api/users', { include_inactive: inactive }) })
  const toggle = useMutation({
    mutationFn: (u: any) => api.patch(`/api/users/${u.id}`, { is_active: !u.is_active }),
    onSuccess: () => { toast('User updated'); qc.invalidateQueries({ queryKey: ['users-admin'] }); qc.invalidateQueries({ queryKey: ['user-options'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  return (
    <div className="card">
      <div className="card-head"><div><h3>Users & roles</h3><p>Admins manage everything; Project Managers manage projects and finance; Team Members work on assigned projects and tasks.</p></div>
        <div className="row"><label className="checkbox small"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Show inactive</label>
          <button className="btn primary sm" onClick={() => setForm({})}><Plus size={14} /> New user</button></div></div>
      <QueryState q={q}>
        <div className="table-wrap"><table className="table">
          <thead><tr><th>Name</th><th>Username</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th /></tr></thead>
          <tbody>{q.data?.items.map((u: any) => (
            <tr key={u.id} className={u.is_active ? '' : 'muted-row'}>
              <td><b>{u.full_name}</b></td><td className="mono">{u.username}</td><td>{u.email}</td><td>{ROLE_LABEL[u.role]}</td>
              <td><Badge text={u.is_active ? 'Active' : 'Inactive'} kind={u.is_active ? 'ok' : ''} /></td><td className="small">{dateTime(u.last_login_at)}</td>
              <td className="actions"><button className="btn xs ghost" onClick={() => setForm(u)}>Edit</button>
                {u.id !== session.user.id && <button className="btn xs ghost" onClick={() => toggle.mutate(u)}>{u.is_active ? 'Deactivate' : 'Activate'}</button>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </QueryState>
      {form && <UserForm user={form.id ? form : null} onClose={() => setForm(null)} />}
    </div>
  )
}

function UserForm({ user, onClose }: { user: any | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const f = useForm({ full_name: user?.full_name ?? '', email: user?.email ?? '', username: user?.username ?? '', role: user?.role ?? 'team_member', password: '' })
  const v = f.values
  const weak = v.password && !(v.password.length >= 8 && /[A-Za-z]/.test(v.password) && /\d/.test(v.password)) ? 'At least 8 characters with letters and numbers' : undefined
  const save = () => f.submit(async () => {
    if (user) await api.patch(`/api/users/${user.id}`, { full_name: v.full_name, role: v.role, ...(v.password ? { password: v.password } : {}) })
    else await api.post('/api/users', v)
    toast(user ? 'User updated' : 'User created')
    qc.invalidateQueries({ queryKey: ['users-admin'] })
    qc.invalidateQueries({ queryKey: ['user-options'] })
    onClose()
  }).catch(() => {})
  return (
    <Modal title={user ? `Edit ${user.full_name}` : 'New user'} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !v.full_name || (!user && (!v.email || !v.username || !v.password)) || !!weak} onClick={save}>{f.submitting ? 'Saving…' : 'Save'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <Field label="Full name" required error={f.errors.full_name}><input className="input" value={v.full_name} onChange={(e) => f.set('full_name', e.target.value)} /></Field>
        <Field label="Email" required error={f.errors.email}><input type="email" className="input" value={v.email} disabled={!!user} onChange={(e) => f.set('email', e.target.value)} /></Field>
        <Field label="Username" required error={f.errors.username}><input className="input" value={v.username} disabled={!!user} onChange={(e) => f.set('username', e.target.value)} /></Field>
        <Field label="Role"><Select value={v.role} onChange={(x) => f.set('role', x)} options={ROLES.map((r) => ({ value: r, label: ROLE_LABEL[r] }))} /></Field>
        <Field label={user ? 'Reset password (optional)' : 'Initial password'} required={!user} error={weak ?? f.errors.password} hint={user ? 'Resetting signs the user out everywhere' : undefined}>
          <input type="password" autoComplete="new-password" className="input" value={v.password} onChange={(e) => f.set('password', e.target.value)} /></Field>
      </div>
    </Modal>
  )
}

function System() {
  const session = useSession()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['settings-system'], queryFn: () => api.get('/api/settings/system') })
  const f = useForm<Record<string, any>>({})
  useEffect(() => { if (q.data) f.setValues({ ...q.data.rules }) }, [q.data]) // eslint-disable-line react-hooks/exhaustive-deps
  const v = f.values
  const save = () => f.submit(async () => {
    await api.put('/api/settings/system/rules', {
      deadline_warning_days: Number(v.deadline_warning_days), quotation_expiry_warning_days: Number(v.quotation_expiry_warning_days),
      missing_update_days: Number(v.missing_update_days), supplier_delay_grace_days: Number(v.supplier_delay_grace_days), enabled_rules: v.enabled_rules,
    })
    toast('Notification rules saved')
    qc.invalidateQueries({ queryKey: ['settings-system'] })
  }).catch(() => {})
  const run = useMutation({
    mutationFn: () => api.post('/api/notifications/run-checks', {}),
    onSuccess: (r: any) => { toast(r.skipped ? 'Another check run is in progress' : 'Checks completed'); qc.invalidateQueries({ queryKey: ['settings-system'] }); qc.invalidateQueries({ queryKey: ['unread-count'] }); qc.invalidateQueries({ queryKey: ['notifications'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const admin = session.permissions.admin
  const i = q.data?.integrations
  return (
    <QueryState q={q}>
      {q.data && <div className="grid grid-2">
        <div className="card card-body">
          <div className="section-title">Integrations</div>
          <table className="table">
            <tbody>
              <tr><td>AI report analysis</td><td>{i.ai.configured ? <Badge text={`Configured · ${i.ai.model}`} kind="ok" /> : <Badge text="Not configured" kind="warn" />}</td></tr>
              <tr><td>Email delivery (SMTP)</td><td>{i.email.configured ? <Badge text="Configured" kind="ok" /> : <Badge text="Not configured" kind="warn" />}</td></tr>
              <tr><td>Background scheduler</td><td>{i.scheduler.enabled ? <Badge text={`Every ${i.scheduler.interval_minutes} min`} kind="ok" /> : <Badge text="Disabled" kind="warn" />}</td></tr>
              <tr><td>OCR for scanned documents</td><td>{i.ocr.configured ? <Badge text="Available" kind="ok" /> : <Badge text="Not installed" kind="warn" />}</td></tr>
              <tr><td>Upload limit</td><td>{q.data.upload_limit_mb} MB</td></tr>
              <tr><td>Environment</td><td className="mono">{q.data.environment}</td></tr>
            </tbody>
          </table>
          {(!i.ai.configured || !i.email.configured || !i.ocr.configured) && <p className="small muted mt-8">
            Integrations are configured by the server administrator in the backend <span className="mono">.env</span> file
            (<span className="mono">ANTHROPIC_API_KEY</span>, <span className="mono">SMTP_*</span>) or by installing Tesseract for OCR. Keys are never sent to the browser.
            Without AI, reports use deterministic template analysis; without email, notifications stay in-app.</p>}
          <div className="section-title mt-16">Scheduler runs</div>
          {Object.keys(i.scheduler.last_runs).length === 0 ? <p className="small muted">No scheduler runs recorded yet.</p> : (
            <ul className="list-plain small">{Object.entries(i.scheduler.last_runs).map(([k, t]) => <li key={k}><span className="mono">{k}</span>: {dateTime(t as string)}</li>)}</ul>
          )}
          {admin && <button className="btn mt-8" disabled={run.isPending} onClick={() => run.mutate()}><Play size={14} /> {run.isPending ? 'Running…' : 'Run reminder & alert checks now'}</button>}
        </div>
        <div className="card card-body">
          <div className="section-title">Notification rules</div>
          {!admin && <Alert kind="info">Only administrators can change these rules.</Alert>}
          {v.enabled_rules && <div className="form">
            {f.formError && <Alert kind="danger">{f.formError}</Alert>}
            <div className="form-grid">
              <Field label="Deadline warning (days before)"><input type="number" min={1} max={60} className="input" disabled={!admin} value={v.deadline_warning_days} onChange={(e) => f.set('deadline_warning_days', e.target.value)} /></Field>
              <Field label="Quotation expiry warning (days)"><input type="number" min={1} max={90} className="input" disabled={!admin} value={v.quotation_expiry_warning_days} onChange={(e) => f.set('quotation_expiry_warning_days', e.target.value)} /></Field>
              <Field label="Missing update after (days)"><input type="number" min={1} max={60} className="input" disabled={!admin} value={v.missing_update_days} onChange={(e) => f.set('missing_update_days', e.target.value)} /></Field>
              <Field label="Supplier delay grace (days)"><input type="number" min={0} max={30} className="input" disabled={!admin} value={v.supplier_delay_grace_days} onChange={(e) => f.set('supplier_delay_grace_days', e.target.value)} /></Field>
            </div>
            <div className="small muted">Enabled automatic alerts:</div>
            <div className="list-plain">{Object.entries(q.data.notification_types as Record<string, string>).map(([k, l]) => (
              <label key={k} className="checkbox"><input type="checkbox" disabled={!admin} checked={v.enabled_rules.includes(k)}
                onChange={(e) => f.set('enabled_rules', e.target.checked ? [...v.enabled_rules, k] : v.enabled_rules.filter((x: string) => x !== k))} /> {l}</label>
            ))}</div>
            {admin && <div><button className="btn primary" disabled={f.submitting} onClick={save}>{f.submitting ? 'Saving…' : 'Save rules'}</button></div>}
          </div>}
        </div>
      </div>}
    </QueryState>
  )
}

function AuditLog() {
  const [page, setPage] = useState(1)
  const [entity, setEntity] = useState('')
  const q = useQuery({ queryKey: ['audit', entity, page], queryFn: () => api.get('/api/audit-logs', { entity_type: entity, page, page_size: 50 }) })
  return (
    <div className="card">
      <div className="filters">
        <Field label="Record type"><Select value={entity} onChange={(v) => { setEntity(v); setPage(1) }} placeholder="All" options={opts([
          'project', 'client', 'quotation', 'quotation_version', 'client_po', 'payment', 'supplier_po', 'supplier_payment', 'bom_item', 'task',
          'project_update', 'document', 'calendar_event', 'user', 'user_settings', 'system_settings', 'report',
        ])} /></Field>
      </div>
      <QueryState q={q}>
        {q.data?.items.length === 0 ? <Empty title="No audit entries" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>When</th><th>User</th><th>Action</th><th>Record</th><th>Changes</th></tr></thead>
            <tbody>{q.data?.items.map((a: any) => (
              <tr key={a.id}>
                <td className="nowrap small">{dateTime(a.created_at)}</td><td>{a.user ?? 'System'}</td><td><Badge text={label(a.action)} kind="outline" /></td>
                <td className="small">{label(a.entity_type)} {a.entity_id && <span className="mono">#{a.entity_id}</span>}</td>
                <td className="small mono" style={{ maxWidth: 480, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{a.changes ? JSON.stringify(a.changes).slice(0, 400) : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {q.data && <Pagination page={page} pageSize={50} total={q.data.total} onPage={setPage} />}
      </QueryState>
    </div>
  )
}
