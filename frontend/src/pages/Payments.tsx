import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Download, Plus } from 'lucide-react'
import { downloadFile, api } from '../lib/api'
import { useClientOptions, useProjectOptions } from '../lib/hooks'
import { label, money } from '../lib/format'
import { Badge, Field, Pagination, QueryState, Select, Stat, Tabs, errorMessage, opts, useDebounced, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'
import { PAYMENT_METHODS, PAYMENT_STATUSES, PAYMENT_TYPES, PaymentForm, PaymentStatusModal, PaymentsTable } from '../components/payments'
import { UploadModal } from '../components/documents'

export default function PaymentsPage() {
  const [tab, setTab] = useState<'summary' | 'list'>('summary')
  const [form, setForm] = useState<any | null>(null)
  return (
    <>
      <PageHead title="Payments" sub="Client receivables (X − Y = Z) and the full payment register. Supplier payments are tracked under BOM Purchase Orders."
        actions={<button className="btn primary" onClick={() => setForm({})}><Plus size={16} /> Record payment</button>} />
      <div className="card mb-16"><div style={{ padding: '0 18px' }}>
        <Tabs value={tab} onChange={setTab} tabs={[{ id: 'summary', label: 'Receivables by project' }, { id: 'list', label: 'Payment register' }]} />
      </div></div>
      {tab === 'summary' ? <Summary /> : <Register onEdit={setForm} />}
      {form && <PaymentForm payment={form.id ? form : undefined} onClose={() => setForm(null)} />}
    </>
  )
}

function Summary() {
  const clients = useClientOptions()
  const [clientId, setClientId] = useState('')
  const [status, setStatus] = useState('')
  const q = useQuery({ queryKey: ['payments-summary', clientId, status], queryFn: () => api.get('/api/payments/summary', { client_id: clientId, status }) })
  return (
    <div className="stack">
      <QueryState q={q}>
        {q.data && <div className="grid grid-3">
          {Object.entries(q.data.totals_by_currency).map(([cur, t]: [string, any]) => (
            <Stat key={cur} label={`Outstanding (Z) · ${cur}`} value={money(t.outstanding, cur)}
              sub={<>X {money(t.contract_value, cur)} − Y {money(t.verified_received, cur)}{Number(t.credit) > 0 && <> · credit {money(t.credit, cur)}</>}{Number(t.overdue_pending) > 0 && <> · overdue {money(t.overdue_pending, cur)}</>}</>} />
          ))}
          {Object.keys(q.data.totals_by_currency).length === 0 && <Stat label="Outstanding" value={money(0)} sub="No projects match" />}
        </div>}
      </QueryState>
      <div className="card">
        <div className="filters">
          <Field label="Client"><Select value={clientId} onChange={setClientId} options={clients.data ?? []} placeholder="All clients" /></Field>
          <Field label="Project status"><Select value={status} onChange={setStatus} options={opts(['planning', 'active', 'on_hold', 'completed', 'cancelled'])} placeholder="All" /></Field>
        </div>
        <QueryState q={q}>
          {q.data && <div className="table-wrap"><table className="table">
            <thead><tr><th>Project</th><th>Client</th><th>Basis for X</th><th className="num">X · Contract</th><th className="num">Y · Verified received</th><th className="num">Z · Outstanding</th><th className="num">Credit</th><th className="num">Awaiting verification</th><th className="num">Overdue expected</th></tr></thead>
            <tbody>{q.data.projects.map((p: any) => (
              <tr key={p.project_id} className={Number(p.overdue_pending) > 0 ? 'overdue' : ''}>
                <td style={{ minWidth: 220 }}><Link to={`/projects/${p.project_id}?tab=payments`} style={{ fontWeight: 600 }}>{p.code}</Link><div className="small muted">{p.name}</div></td>
                <td className="small" style={{ minWidth: 160 }}>{p.client}</td>
                <td><Badge text={label(p.contract_basis)} kind={p.contract_basis === 'verified_client_po' ? 'ok' : p.contract_basis === 'not_set' ? 'danger' : 'warn'} /></td>
                <td className="num">{money(p.contract_value, p.currency)}</td>
                <td className="num">{money(p.verified_received, p.currency)}</td>
                <td className="num"><b>{money(p.outstanding, p.currency)}</b></td>
                <td className="num">{Number(p.credit) > 0 ? <Badge text={money(p.credit, p.currency)} kind="info" /> : '—'}</td>
                <td className="num">{money(p.unverified_recorded, p.currency)}</td>
                <td className="num">{Number(p.overdue_pending) > 0 ? <span style={{ color: 'var(--danger)' }}>{money(p.overdue_pending, p.currency)} ({p.overdue_count})</span> : '—'}</td>
              </tr>
            ))}</tbody>
          </table></div>}
          {q.data && <p className="small muted" style={{ padding: '0 18px 14px' }}>{q.data.note}</p>}
        </QueryState>
      </div>
    </div>
  )
}

function Register({ onEdit }: { onEdit: (p: any) => void }) {
  const toast = useToast()
  const projects = useProjectOptions(true)
  const clients = useClientOptions()
  const [qs, setQs] = useState('')
  const dq = useDebounced(qs)
  const [page, setPage] = useState(1)
  const [f, setF] = useState({ project_id: '', client_id: '', status: '', method: '', payment_type: '', date_from: '', date_to: '', overdue: false })
  const [statusFor, setStatusFor] = useState<any | null>(null)
  const [attach, setAttach] = useState<any | null>(null)
  const set = (k: string, v: any) => { setF((s) => ({ ...s, [k]: v })); setPage(1) }
  const params = { ...f, q: dq, page, page_size: 25 }
  const list = useQuery({ queryKey: ['payments', params], queryFn: () => api.get('/api/payments', params) })
  const exp = (format: 'csv' | 'xlsx') => downloadFile('/api/payments/export', `client-payments.${format}`,
    { format, project_id: f.project_id, client_id: f.client_id, status: f.status, date_from: f.date_from, date_to: f.date_to }).catch((e) => toast(errorMessage(e), 'error'))
  return (
    <div className="card">
      <div className="filters">
        <Field label="Search" className="grow"><input className="input" placeholder="Reference, invoice, milestone…" value={qs} onChange={(e) => { setQs(e.target.value); setPage(1) }} /></Field>
        <Field label="Project"><Select value={f.project_id} onChange={(v) => set('project_id', v)} options={projects.data ?? []} placeholder="All" /></Field>
        <Field label="Client"><Select value={f.client_id} onChange={(v) => set('client_id', v)} options={clients.data ?? []} placeholder="All" /></Field>
        <Field label="Status"><Select value={f.status} onChange={(v) => set('status', v)} options={opts(PAYMENT_STATUSES)} placeholder="All" /></Field>
        <Field label="Type"><Select value={f.payment_type} onChange={(v) => set('payment_type', v)} options={opts(PAYMENT_TYPES)} placeholder="All" /></Field>
        <Field label="Method"><Select value={f.method} onChange={(v) => set('method', v)} options={opts(PAYMENT_METHODS)} placeholder="All" /></Field>
        <Field label="From"><input type="date" className="input" value={f.date_from} onChange={(e) => set('date_from', e.target.value)} /></Field>
        <Field label="To"><input type="date" className="input" value={f.date_to} onChange={(e) => set('date_to', e.target.value)} /></Field>
        <label className="checkbox"><input type="checkbox" checked={f.overdue} onChange={(e) => set('overdue', e.target.checked)} /> Overdue</label>
        <div className="row" style={{ alignSelf: 'flex-end' }}>
          <button className="btn sm" onClick={() => exp('csv')}><Download size={14} /> CSV</button>
          <button className="btn sm" onClick={() => exp('xlsx')}><Download size={14} /> Excel</button>
        </div>
      </div>
      <QueryState q={list}>
        {list.data && <PaymentsTable rows={list.data.items} showProject editable onEdit={onEdit} onStatus={setStatusFor} onAttach={setAttach} />}
        {list.data && <Pagination page={page} pageSize={25} total={list.data.total} onPage={setPage} />}
      </QueryState>
      {statusFor && <PaymentStatusModal payment={statusFor} onClose={() => setStatusFor(null)} />}
      {attach && <UploadModal projectId={attach.project_id} category="payment_proof" links={{ payment_id: attach.id }} title={`Attach proof for payment #${attach.id}`} onClose={() => setAttach(null)} />}
    </div>
  )
}
