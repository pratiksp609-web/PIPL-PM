import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Pencil, Plus } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useProjectOptions } from '../lib/hooks'
import { money } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, QueryState, Select, Tabs, clean, errorMessage, useForm, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'
import { ProjectProcurementPanel } from '../components/procurement'

export default function ProcurementPage() {
  const session = useSession()
  const [sp, setSp] = useSearchParams()
  const projects = useProjectOptions()
  const pid = sp.get('project') ?? ''
  const [tab, setTab] = useState<'projects' | 'suppliers'>('projects')
  const project = (projects.data ?? []).find((p: any) => String(p.value) === pid) as any
  return (
    <>
      <PageHead title="BOM Purchase Orders" sub="Bill of materials, supplier purchase orders, deliveries and supplier payments. Kept separate from client receivables." />
      <div className="card mb-16"><div style={{ padding: '0 18px' }}>
        <Tabs value={tab} onChange={setTab} tabs={[{ id: 'projects', label: 'Projects' }, { id: 'suppliers', label: 'Suppliers' }]} />
      </div></div>
      {tab === 'suppliers' ? <Suppliers /> : (
        <div className="stack">
          <div className="card"><div className="filters">
            <Field label="Project" className="grow"><Select value={pid} onChange={(v) => setSp(v ? { project: v } : {}, { replace: true })} options={projects.data ?? []} placeholder={session.permissions.finance ? 'All projects (summary)' : 'Select a project'} /></Field>
            {pid && <Link className="btn" style={{ alignSelf: 'flex-end' }} to={`/projects/${pid}?tab=bom`}>Open in project workspace</Link>}
          </div></div>
          {pid && project ? <ProjectProcurementPanel key={pid} projectId={Number(pid)} currency={project.currency} editable={session.permissions.manage_projects} />
            : session.permissions.finance ? <CompanySummary onPick={(id) => setSp({ project: String(id) })} />
            : <div className="card"><Empty title="Select a project" text="Choose a project to see its bill of materials and procurement status." /></div>}
        </div>
      )}
    </>
  )
}

function CompanySummary({ onPick }: { onPick: (id: number) => void }) {
  const q = useQuery({ queryKey: ['procurement', 'summary'], queryFn: () => api.get('/api/procurement/summary') })
  return (
    <div className="card">
      <div className="card-head"><div><h3>Procurement across projects</h3><p>{q.data?.note}</p></div></div>
      <QueryState q={q}>
        {q.data?.projects.length === 0 ? <Empty title="No BOM items or supplier POs yet" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Project</th><th className="num">BOM items</th><th className="num">Estimated</th><th className="num">Committed (POs)</th><th className="num">Paid to suppliers</th><th className="num">Supplier balance</th><th className="num">Pending items</th><th>Late deliveries</th><th>Missing PO docs</th></tr></thead>
            <tbody>{q.data?.projects.map((p: any) => (
              <tr key={p.project_id} className={p.late_deliveries.length ? 'overdue' : ''}>
                <td style={{ minWidth: 220 }}><button className="link-btn" style={{ fontWeight: 600 }} onClick={() => onPick(p.project_id)}>{p.code}</button><div className="small muted">{p.name}</div></td>
                <td className="num">{p.bom_item_count}</td>
                <td className="num">{money(p.estimated_cost, p.currency)}</td>
                <td className="num">{money(p.committed_cost, p.currency)}</td>
                <td className="num">{money(p.supplier_paid, p.currency)}</td>
                <td className="num">{money(p.supplier_outstanding, p.currency)}</td>
                <td className="num">{p.pending_procurement_count}</td>
                <td>{p.late_deliveries.length ? <Badge text={`${p.late_deliveries.length} late`} kind="danger" /> : '—'}</td>
                <td>{p.pos_missing_documents.length ? <Badge text={String(p.pos_missing_documents.length)} kind="warn" /> : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </QueryState>
    </div>
  )
}

function Suppliers() {
  const session = useSession()
  const qc = useQueryClient()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [archived, setArchived] = useState(false)
  const [form, setForm] = useState<any | null>(null)
  const list = useQuery({ queryKey: ['suppliers', q, archived], queryFn: () => api.get('/api/suppliers', { q, include_archived: archived, page_size: 200 }) })
  const arch = useMutation({
    mutationFn: ({ id, archived }: { id: number; archived: boolean }) => api.post(`/api/suppliers/${id}/archive`, {}, { archived }),
    onSuccess: () => { toast('Supplier updated'); qc.invalidateQueries({ queryKey: ['suppliers'] }); qc.invalidateQueries({ queryKey: ['supplier-options'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const canManage = session.permissions.manage_projects
  return (
    <div className="card">
      <div className="filters">
        <Field label="Search" className="grow"><input className="input" placeholder="Name, contact, GSTIN" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
        <label className="checkbox"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Include archived</label>
        {canManage && <button className="btn primary" style={{ alignSelf: 'flex-end' }} onClick={() => setForm({})}><Plus size={15} /> New supplier</button>}
      </div>
      <QueryState q={list}>
        {list.data?.items.length === 0 ? <Empty title="No suppliers" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Supplier</th><th>Contact</th><th>Email / phone</th><th>GSTIN</th><th /></tr></thead>
            <tbody>{list.data?.items.map((s: any) => (
              <tr key={s.id} className={s.archived_at ? 'muted-row' : ''}>
                <td><b>{s.name}</b>{s.archived_at && <> <Badge text="Archived" /></>}{s.is_sample && <> <Badge text="Sample" kind="info" /></>}</td>
                <td>{s.contact_person ?? '—'}</td>
                <td className="small">{s.email ?? '—'}<div>{s.phone}</div></td>
                <td className="mono">{s.gstin ?? '—'}</td>
                <td className="actions">{canManage && <>
                  <button className="btn xs ghost" aria-label="Edit" onClick={() => setForm(s)}><Pencil size={14} /></button>
                  <button className="btn xs ghost" aria-label={s.archived_at ? 'Restore' : 'Archive'} onClick={() => arch.mutate({ id: s.id, archived: !s.archived_at })}>{s.archived_at ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>
                </>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </QueryState>
      {form && <SupplierForm supplier={form.id ? form : null} onClose={() => setForm(null)} />}
    </div>
  )
}

function SupplierForm({ supplier, onClose }: { supplier: any | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const f = useForm({ name: supplier?.name ?? '', contact_person: supplier?.contact_person ?? '', email: supplier?.email ?? '', phone: supplier?.phone ?? '', address: supplier?.address ?? '', gstin: supplier?.gstin ?? '' })
  const v = f.values
  const save = () => f.submit(async () => {
    if (supplier) await api.patch(`/api/suppliers/${supplier.id}`, clean(v))
    else await api.post('/api/suppliers', clean(v))
    toast(supplier ? 'Supplier updated' : 'Supplier added')
    qc.invalidateQueries({ queryKey: ['suppliers'] })
    qc.invalidateQueries({ queryKey: ['supplier-options'] })
    onClose()
  }).catch(() => {})
  return (
    <Modal title={supplier ? 'Edit supplier' : 'New supplier'} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !v.name.trim()} onClick={save}>{f.submitting ? 'Saving…' : 'Save'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <div className="form-grid">
          <Field label="Supplier name" required className="span-2" error={f.errors.name}><input className="input" value={v.name} onChange={(e) => f.set('name', e.target.value)} /></Field>
          <Field label="Contact person"><input className="input" value={v.contact_person} onChange={(e) => f.set('contact_person', e.target.value)} /></Field>
          <Field label="GSTIN" error={f.errors.gstin}><input className="input mono" value={v.gstin} onChange={(e) => f.set('gstin', e.target.value.toUpperCase())} /></Field>
          <Field label="Email" error={f.errors.email}><input type="email" className="input" value={v.email} onChange={(e) => f.set('email', e.target.value)} /></Field>
          <Field label="Phone" error={f.errors.phone}><input className="input" value={v.phone} onChange={(e) => f.set('phone', e.target.value)} /></Field>
          <Field label="Address" className="span-2"><textarea className="input" value={v.address} onChange={(e) => f.set('address', e.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  )
}
