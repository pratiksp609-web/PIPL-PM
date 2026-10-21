import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Building2, Pencil, Plus } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { useSession } from '../lib/auth'
import { Alert, Badge, Empty, Field, Modal, Pagination, QueryState, clean, errorMessage, useConfirm, useDebounced, useForm, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'

export default function Clients() {
  const session = useSession()
  const [q, setQ] = useState('')
  const [archived, setArchived] = useState(false)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<any | null>(null)
  const dq = useDebounced(q)
  const nav = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const list = useQuery({ queryKey: ['clients', dq, archived, page], queryFn: () => api.get('/api/clients', { q: dq, include_archived: archived, page, page_size: 20 }) })
  const archive = useMutation({
    mutationFn: ({ id, archived }: { id: number; archived: boolean }) => api.post(`/api/clients/${id}/archive`, {}, { archived }),
    onSuccess: () => { toast('Client updated'); qc.invalidateQueries({ queryKey: ['clients'] }); qc.invalidateQueries({ queryKey: ['client-options'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const canManage = session.permissions.manage_projects
  return (
    <>
      <PageHead title="Clients" sub="Client companies, contacts, GSTIN and their projects."
        actions={canManage && <button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> New client</button>} />
      <div className="card">
        <div className="filters">
          <Field label="Search" className="grow"><input className="input" placeholder="Company, contact, email, GSTIN…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
          <label className="checkbox"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> Include archived</label>
        </div>
        <QueryState q={list}>
          {list.data?.items.length === 0 ? (
            <Empty icon={<Building2 size={36} />} title="No clients found" text={dq ? 'Try another search.' : 'Add your first client.'} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Company</th><th>Contact</th><th>Email / phone</th><th>GSTIN</th><th className="num">Projects</th><th /></tr></thead>
                <tbody>
                  {list.data?.items.map((c: any) => (
                    <tr key={c.id} className={`clickable ${c.archived_at ? 'muted-row' : ''}`} onClick={() => nav(`/clients/${c.id}`)}>
                      <td><Link to={`/clients/${c.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 600 }}>{c.company_name}</Link><div className="small muted">{c.name}</div>{c.archived_at && <Badge text="Archived" />}</td>
                      <td>{c.contact_person ?? '—'}</td>
                      <td>{c.email ?? '—'}<div className="small muted">{c.phone}</div></td>
                      <td className="mono">{c.gstin ?? '—'}</td>
                      <td className="num">{c.project_count}</td>
                      <td className="actions" onClick={(e) => e.stopPropagation()}>
                        {canManage && <>
                          <button className="btn xs ghost" onClick={() => setEditing(c)} aria-label="Edit"><Pencil size={14} /></button>
                          <button className="btn xs ghost" aria-label={c.archived_at ? 'Restore' : 'Archive'} onClick={async () => {
                            if (await confirm({ title: c.archived_at ? 'Restore client?' : 'Archive client?', message: c.archived_at ? 'The client will be available for new projects again.' : 'Archived clients cannot be selected for new projects. Existing records are kept.', danger: !c.archived_at, confirmText: c.archived_at ? 'Restore' : 'Archive' }))
                              archive.mutate({ id: c.id, archived: !c.archived_at })
                          }}>{c.archived_at ? <ArchiveRestore size={14} /> : <Archive size={14} />}</button>
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
      {editing && <ClientForm client={editing.id ? editing : null} onClose={() => setEditing(null)} />}
    </>
  )
}

export function ClientForm({ client, onClose }: { client: any | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [dupId, setDupId] = useState<number | null>(null)
  const f = useForm({
    name: client?.name ?? '', company_name: client?.company_name ?? '', contact_person: client?.contact_person ?? '', email: client?.email ?? '',
    phone: client?.phone ?? '', billing_address: client?.billing_address ?? '', gstin: client?.gstin ?? '', notes: client?.notes ?? '',
  })
  const v = f.values
  const gstinBad = v.gstin && !/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/.test(v.gstin.toUpperCase())
  const save = () => f.submit(async () => {
    setDupId(null)
    try {
      const body = clean(v)
      if (client) await api.patch(`/api/clients/${client.id}`, body)
      else await api.post('/api/clients', body)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setDupId((e.details as any)?.existing_client_id ?? null)
      throw e
    }
    toast(client ? 'Client updated' : 'Client created')
    qc.invalidateQueries({ queryKey: ['clients'] })
    qc.invalidateQueries({ queryKey: ['client'] })
    qc.invalidateQueries({ queryKey: ['client-options'] })
    onClose()
  }).catch(() => {})
  const e = f.errors
  return (
    <Modal title={client ? 'Edit client' : 'New client'} onClose={onClose} size="lg"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !v.name || !v.company_name || !!gstinBad} onClick={save}>{f.submitting ? 'Saving…' : 'Save client'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError} {dupId && <Link to={`/clients/${dupId}`} onClick={onClose}>Open existing client</Link>}</Alert>}
        <div className="form-grid">
          <Field label="Client name" required error={e.name}><input className="input" value={v.name} onChange={(x) => f.set('name', x.target.value)} /></Field>
          <Field label="Company name" required error={e.company_name} hint="Must be unique"><input className="input" value={v.company_name} onChange={(x) => f.set('company_name', x.target.value)} /></Field>
          <Field label="Contact person" error={e.contact_person}><input className="input" value={v.contact_person} onChange={(x) => f.set('contact_person', x.target.value)} /></Field>
          <Field label="Email" error={e.email}><input type="email" className="input" value={v.email} onChange={(x) => f.set('email', x.target.value)} /></Field>
          <Field label="Phone" error={e.phone}><input className="input" value={v.phone} onChange={(x) => f.set('phone', x.target.value)} /></Field>
          <Field label="GSTIN" error={e.gstin || (gstinBad ? 'Enter a valid 15-character GSTIN' : undefined)} hint="Optional, e.g. 27ABCDE1234F1Z5">
            <input className={`input mono ${gstinBad ? 'invalid' : ''}`} value={v.gstin} maxLength={15} onChange={(x) => f.set('gstin', x.target.value.toUpperCase())} />
          </Field>
          <Field label="Billing address" className="span-2" error={e.billing_address}><textarea className="input" value={v.billing_address} onChange={(x) => f.set('billing_address', x.target.value)} /></Field>
          <Field label="Notes" className="span-2" error={e.notes}><textarea className="input" value={v.notes} onChange={(x) => f.set('notes', x.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  )
}
