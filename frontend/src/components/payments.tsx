import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Paperclip, Plus, ShieldCheck } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { date, label, money, todayIso } from '../lib/format'
import { useProjectOptions } from '../lib/hooks'
import { Alert, Badge, Empty, Field, Modal, QueryState, Select, clean, errorMessage, opts, useForm, useToast } from './ui'
import { UploadModal } from './documents'

export const PAYMENT_STATUSES = ['recorded', 'pending', 'verified', 'failed', 'reversed'] as const
export const PAYMENT_TYPES = ['advance', 'milestone', 'partial', 'final', 'other'] as const
export const PAYMENT_METHODS = ['bank_transfer', 'cheque', 'upi', 'cash', 'card', 'other'] as const
const BASIS: Record<string, string> = {
  verified_client_po: 'Verified client PO', approved_quotation: 'Approved quotation (no verified PO yet)',
  project_contract_value: 'Project contract value (no PO/quotation)', not_set: 'Not set',
}

export function XYZCard({ r }: { r: any }) {
  const c = r.currency
  return (
    <div className="card">
      <div className="card-head"><div><h3>Client receivable · X − Y = Z</h3><p>Calculated on the server from verified records. Supplier payments are excluded.</p></div>
        <Badge text={`Basis: ${BASIS[r.contract_basis] ?? r.contract_basis}`} kind={r.contract_basis === 'verified_client_po' ? 'ok' : 'warn'} /></div>
      <div className="card-body">
        <div className="xyz">
          <div className="term"><div className="k">X · Approved contract value</div><div className="v">{money(r.contract_value, c)}</div><div className="d">{BASIS[r.contract_basis]}</div></div>
          <div className="op">−</div>
          <div className="term"><div className="k">Y · Verified payments received</div><div className="v">{money(r.verified_received, c)}</div><div className="d">{r.payment_count} payment record(s) in total</div></div>
          <div className="op">=</div>
          <div className="term z"><div className="k">Z · Outstanding receivable</div><div className="v">{money(r.outstanding, c)}</div><div className="d">{Number(r.overdue_pending) > 0 ? `${money(r.overdue_pending, c)} overdue` : 'Nothing overdue'}</div></div>
        </div>
        {Number(r.credit) > 0 && <div className="credit-banner">Overpayment / credit: {money(r.credit, c)} — verified payments exceed the contract value. Z is shown as zero and the excess is tracked separately.</div>}
        <div className="row mt-16" style={{ gap: 8 }}>
          <span className="kv-chip">Recorded, awaiting verification <b>{money(r.unverified_recorded, c)}</b></span>
          <span className="kv-chip">Expected (pending) <b>{money(r.expected_pending, c)}</b></span>
          <span className="kv-chip">Failed / reversed <b>{money(r.failed_or_reversed, c)}</b></span>
        </div>
        {r.notes?.length > 0 && <ul className="list-dots small muted mt-8">{r.notes.map((n: string) => <li key={n}>{n}</li>)}</ul>}
      </div>
    </div>
  )
}

export function PaymentForm({ projectId, payment, onClose }: { projectId?: number; payment?: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const projects = useProjectOptions()
  const [confirmNeeded, setConfirmNeeded] = useState<{ code: string; message: string } | null>(null)
  const f = useForm({
    project_id: String(projectId ?? payment?.project_id ?? ''), status: payment ? payment.status : 'recorded', amount: payment?.amount ?? '',
    payment_date: payment?.payment_date ?? todayIso(), due_date: payment?.due_date ?? '', payment_type: payment?.payment_type ?? 'partial',
    milestone_label: payment?.milestone_label ?? '', method: payment?.method ?? 'bank_transfer', transaction_reference: payment?.transaction_reference ?? '',
    bank_reference: payment?.bank_reference ?? '', invoice_reference: payment?.invoice_reference ?? '', notes: payment?.notes ?? '', client_po_id: payment?.client_po_id ?? '',
  })
  const v = f.values
  const pos = useQuery({
    queryKey: ['client-pos', Number(v.project_id)], queryFn: () => api.get('/api/client-pos', { project_id: v.project_id }), enabled: !!v.project_id,
  })
  const pending = v.status === 'pending'
  const amountErr = v.amount !== '' && Number(v.amount) <= 0 ? 'Amount must be greater than zero' : undefined
  const dateErr = !pending && v.payment_date > todayIso() ? 'Payment date cannot be in the future' : undefined
  const save = (overrides: { allow_overpayment?: boolean; confirm_possible_duplicate?: boolean } = {}) => f.submit(async () => {
    const base = clean({
      amount: v.amount, payment_type: v.payment_type, milestone_label: v.milestone_label, method: pending ? null : v.method,
      transaction_reference: v.transaction_reference, bank_reference: v.bank_reference, invoice_reference: v.invoice_reference, notes: v.notes,
      client_po_id: Number(v.client_po_id) || null, payment_date: pending ? null : v.payment_date, due_date: v.due_date,
    })
    try {
      if (payment) await api.patch(`/api/payments/${payment.id}`, { ...base, allow_overpayment: !!overrides.allow_overpayment })
      else await api.post('/api/payments', { ...base, project_id: Number(v.project_id), status: v.status, ...overrides })
    } catch (e) {
      if (e instanceof ApiError && ['overpayment', 'possible_duplicate'].includes(e.code)) setConfirmNeeded({ code: e.code, message: e.message })
      throw e
    }
    toast(payment ? 'Payment updated' : pending ? 'Expected payment scheduled' : 'Payment recorded — verify it to include it in Y')
    ;['payments', 'payments-project', 'payments-summary', 'project', 'dashboard'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
    onClose()
  }).catch(() => {})
  const e = f.errors
  return (
    <Modal title={payment ? `Edit payment #${payment.id}` : 'Record client payment'} onClose={onClose} size="lg"
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        {confirmNeeded ? (
          <button className="btn accent" disabled={f.submitting} onClick={() => { const c = confirmNeeded; setConfirmNeeded(null); save(c.code === 'overpayment' ? { allow_overpayment: true } : { confirm_possible_duplicate: true }) }}>
            {confirmNeeded.code === 'overpayment' ? 'Confirm overpayment' : 'Confirm separate payment'}
          </button>
        ) : (
          <button className="btn primary" disabled={f.submitting || !v.project_id || !v.amount || !!amountErr || !!dateErr || (pending && !v.due_date)} onClick={() => save()}>{f.submitting ? 'Saving…' : 'Save payment'}</button>
        )}
      </>}>
      <div className="form">
        {f.formError && <Alert kind={confirmNeeded ? 'warn' : 'danger'}>{f.formError}</Alert>}
        <div className="form-grid">
          {!projectId && !payment && <Field label="Project" required className="span-2"><Select value={v.project_id} onChange={(x) => f.set('project_id', x)} options={projects.data ?? []} placeholder="Select project" /></Field>}
          {!payment && (
            <Field label="Type of entry" className="span-2">
              <div className="seg">
                <button className={!pending ? 'active' : ''} onClick={() => f.set('status', 'recorded')}>Payment received</button>
                <button className={pending ? 'active' : ''} onClick={() => f.set('status', 'pending')}>Expected payment (due)</button>
              </div>
            </Field>
          )}
          <Field label="Amount" required error={e.amount || amountErr}><input type="number" min={0.01} step="0.01" className="input" value={v.amount} onChange={(x) => f.set('amount', x.target.value)} /></Field>
          {!pending
            ? <Field label="Payment date" required error={e.payment_date || dateErr}><input type="date" className="input" max={todayIso()} value={v.payment_date} onChange={(x) => f.set('payment_date', x.target.value)} /></Field>
            : <Field label="Due date" required error={e.due_date}><input type="date" className="input" value={v.due_date} onChange={(x) => f.set('due_date', x.target.value)} /></Field>}
          <Field label="Payment type"><Select value={v.payment_type} onChange={(x) => f.set('payment_type', x)} options={opts(PAYMENT_TYPES)} /></Field>
          <Field label="Milestone / label"><input className="input" value={v.milestone_label} onChange={(x) => f.set('milestone_label', x.target.value)} placeholder="e.g. 30% advance" /></Field>
          {!pending && <Field label="Method"><Select value={v.method} onChange={(x) => f.set('method', x)} options={opts(PAYMENT_METHODS)} /></Field>}
          <Field label="Client PO"><Select value={v.client_po_id} onChange={(x) => f.set('client_po_id', x)} options={((pos.data?.items ?? []) as any[]).map((p) => ({ value: p.id, label: `${p.po_number} (${label(p.status)})` }))} placeholder="Not linked" /></Field>
          {!pending && <Field label="Transaction reference (UTR / cheque no.)" error={e.transaction_reference} hint="Must be unique; prevents duplicate entries"><input className="input mono" value={v.transaction_reference} onChange={(x) => f.set('transaction_reference', x.target.value)} /></Field>}
          {!pending && <Field label="Bank reference"><input className="input mono" value={v.bank_reference} onChange={(x) => f.set('bank_reference', x.target.value)} /></Field>}
          <Field label="Invoice reference"><input className="input mono" value={v.invoice_reference} onChange={(x) => f.set('invoice_reference', x.target.value)} /></Field>
          <Field label="Notes" className="span-2"><textarea className="input" value={v.notes} onChange={(x) => f.set('notes', x.target.value)} /></Field>
        </div>
        {!payment && !pending && <Alert kind="info">New payments start as <b>Recorded</b>. They count toward Y only after someone verifies them against the bank statement.</Alert>}
      </div>
    </Modal>
  )
}

const NEXT: Record<string, string[]> = { pending: ['recorded', 'verified', 'failed'], recorded: ['verified', 'failed', 'pending'], verified: ['reversed'], failed: [], reversed: [] }

export function PaymentStatusModal({ payment, onClose }: { payment: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const options = NEXT[payment.status] ?? []
  const [status, setStatus] = useState(options[0] ?? '')
  const [paymentDate, setPaymentDate] = useState(payment.payment_date ?? todayIso())
  const [notes, setNotes] = useState('')
  const [allowOver, setAllowOver] = useState(false)
  const [overMsg, setOverMsg] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: () => api.post(`/api/payments/${payment.id}/status`, { status, payment_date: ['recorded', 'verified'].includes(status) ? paymentDate : null, notes: notes || null, allow_overpayment: allowOver }),
    onSuccess: () => {
      toast(`Payment marked ${label(status)}`)
      ;['payments', 'payments-project', 'payments-summary', 'project', 'dashboard'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      onClose()
    },
    onError: (e) => { if (e instanceof ApiError && e.code === 'overpayment') setOverMsg(e.message) },
  })
  return (
    <Modal title={`Payment #${payment.id} · ${money(payment.amount, payment.currency)}`} onClose={onClose} size="sm"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className={`btn ${['failed', 'reversed'].includes(status) ? 'danger' : 'primary'}`} disabled={!status || m.isPending || (!!overMsg && !allowOver)} onClick={() => m.mutate()}>{m.isPending ? 'Saving…' : 'Confirm'}</button></>}>
      <div className="form">
        {m.error && !overMsg && <Alert kind="danger">{errorMessage(m.error)}</Alert>}
        {overMsg && <><Alert kind="warn">{overMsg}</Alert><label className="checkbox"><input type="checkbox" checked={allowOver} onChange={(e) => setAllowOver(e.target.checked)} /> Record it anyway and show the excess as credit</label></>}
        <p>Current status: <Badge value={payment.status} /></p>
        {options.length === 0 ? <Alert kind="info">A {payment.status} payment is final and cannot change. Record a new payment if needed.</Alert> : <>
          <Field label="New status"><Select value={status} onChange={setStatus} options={options.map((o) => ({ value: o, label: label(o) }))} /></Field>
          {['recorded', 'verified'].includes(status) && <Field label="Date received"><input type="date" className="input" max={todayIso()} value={paymentDate} onChange={(e) => setPaymentDate(e.target.value)} /></Field>}
          {status === 'verified' && <Alert kind="info"><ShieldCheck size={14} /> Verified payments are included in Y and lock the record against edits.</Alert>}
          {status === 'reversed' && <Alert kind="warn">Reversing removes this amount from Y. The record is kept for history.</Alert>}
          <Field label="Notes" hint="Recorded in the audit history"><textarea className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
        </>}
      </div>
    </Modal>
  )
}

export function PaymentsTable({ rows, showProject, editable, onEdit, onStatus, onAttach }: {
  rows: any[]; showProject?: boolean; editable: boolean; onEdit: (p: any) => void; onStatus: (p: any) => void; onAttach?: (p: any) => void
}) {
  if (!rows.length) return <Empty title="No payments" text="Record received payments and expected milestone payments here." />
  return (
    <div className="table-wrap"><table className="table">
      <thead><tr><th>Date</th>{showProject && <th>Project</th>}<th>Type</th><th>Status</th><th>Method</th><th>References</th><th className="num">Amount</th><th /></tr></thead>
      <tbody>{rows.map((p) => (
        <tr key={p.id} className={`${p.is_overdue ? 'overdue' : ''} ${['failed', 'reversed'].includes(p.status) ? 'muted-row' : ''}`}>
          <td className="nowrap">{p.payment_date ? date(p.payment_date) : <>Due {date(p.due_date)}</>}{p.is_overdue && <div><Badge text="Overdue" kind="danger" /></div>}</td>
          {showProject && <td className="small" style={{ minWidth: 200 }}>{p.project_code}<div className="muted">{p.project_name}</div></td>}
          <td>{label(p.payment_type)}{p.milestone_label && <div className="small muted">{p.milestone_label}</div>}</td>
          <td><Badge value={p.status} /></td>
          <td>{label(p.method)}</td>
          <td className="small mono">{p.transaction_reference && <div>Txn {p.transaction_reference}</div>}{p.bank_reference && <div>Bank {p.bank_reference}</div>}{p.invoice_reference && <div>Inv {p.invoice_reference}</div>}{!p.transaction_reference && !p.bank_reference && !p.invoice_reference && '—'}</td>
          <td className="num"><b>{money(p.amount, p.currency)}</b></td>
          <td className="actions">
            {editable && ['recorded', 'pending'].includes(p.status) && <button className="btn xs ghost" onClick={() => onEdit(p)}>Edit</button>}
            {editable && !['failed', 'reversed'].includes(p.status) && <button className="btn xs" onClick={() => onStatus(p)}>{p.status === 'recorded' ? 'Verify…' : 'Status'}</button>}
            {editable && onAttach && <button className="btn xs ghost" title="Attach proof" aria-label="Attach proof" onClick={() => onAttach(p)}><Paperclip size={13} /></button>}
          </td>
        </tr>
      ))}</tbody>
    </table></div>
  )
}

export function ProjectPaymentsPanel({ projectId, editable }: { projectId: number; editable: boolean }) {
  const q = useQuery({ queryKey: ['payments-project', projectId], queryFn: () => api.get(`/api/projects/${projectId}/payments`) })
  const [form, setForm] = useState<any | null>(null)
  const [statusFor, setStatusFor] = useState<any | null>(null)
  const [attach, setAttach] = useState<any | null>(null)
  return (
    <QueryState q={q}>
      {q.data && (
        <div className="stack">
          <XYZCard r={q.data.receivable} />
          <div className="card">
            <div className="card-head"><div><h3>Payment history</h3><p>Partial, advance, milestone and final payments. Every change is audit logged.</p></div>
              {editable && <button className="btn primary sm" onClick={() => setForm({})}><Plus size={14} /> Record payment</button>}</div>
            <PaymentsTable rows={q.data.payments} editable={editable} onEdit={setForm} onStatus={setStatusFor} onAttach={setAttach} />
          </div>
          {form && <PaymentForm projectId={projectId} payment={form.id ? form : undefined} onClose={() => setForm(null)} />}
          {statusFor && <PaymentStatusModal payment={statusFor} onClose={() => setStatusFor(null)} />}
          {attach && <UploadModal projectId={projectId} category="payment_proof" links={{ payment_id: attach.id }} title={`Attach proof for payment #${attach.id}`} onClose={() => setAttach(null)} />}
        </div>
      )}
    </QueryState>
  )
}
