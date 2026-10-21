import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, PackageCheck, Paperclip, Pencil, Plus, Trash2, Truck, Wallet } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useSupplierOptions } from '../lib/hooks'
import { CURRENCIES, date, label, money, num, todayIso } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, QueryState, Select, Stat, clean, errorMessage, opts, useConfirm, useForm, useToast } from './ui'
import { DocLink, UploadModal } from './documents'
import { PAYMENT_METHODS } from './payments'

export const PROCUREMENT_STATUSES = ['pending', 'rfq', 'ordered', 'partially_received', 'received', 'cancelled', 'delayed'] as const
export const SPO_STATUSES = ['draft', 'ordered', 'partially_received', 'received', 'cancelled', 'delayed'] as const

const invalidate = (qc: ReturnType<typeof useQueryClient>) =>
  ['bom', 'spos', 'procurement', 'supplier-payments', 'project'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))

export function ProcurementSummary({ s, currency }: { s: any; currency: string }) {
  return (
    <div className="stack">
      <div className="grid grid-4">
        <Stat label="Estimated BOM cost" value={money(s.estimated_cost, currency)} sub={`${s.bom_item_count} BOM items`} />
        <Stat label="Committed (supplier POs)" value={money(s.committed_cost, currency)} sub={<>Pre-tax variance {money(s.variance_pre_tax, currency)}</>} tone={Number(s.variance_pre_tax) > 0 ? 'warn' : ''} />
        <Stat label="Paid to suppliers" value={money(s.supplier_paid, currency)} sub={`Supplier balance ${money(s.supplier_outstanding, currency)}`} />
        <Stat label="Pending / late" value={`${s.pending_procurement_count} / ${s.late_deliveries.length}`} sub="Items without PO / late deliveries" tone={s.late_deliveries.length ? 'danger' : ''} />
      </div>
      {(s.late_deliveries.length > 0 || s.pos_missing_documents.length > 0 || s.late_bom_items.length > 0) && (
        <div className="grid grid-3">
          {s.late_deliveries.length > 0 && <Alert kind="danger"><b>Late deliveries:</b> {s.late_deliveries.map((d: any) => `${d.po_number} (${d.supplier}, ${d.days_late} d)`).join(', ')}</Alert>}
          {s.late_bom_items.length > 0 && <Alert kind="warn"><b>Items past required date:</b> {s.late_bom_items.map((i: any) => i.item_name).join(', ')}</Alert>}
          {s.pos_missing_documents.length > 0 && <Alert kind="warn"><b>Supplier POs missing documents:</b> {s.pos_missing_documents.map((p: any) => p.po_number).join(', ')}</Alert>}
        </div>
      )}
      <p className="small muted">{s.note} Supplier payments are never included in client receivables.</p>
    </div>
  )
}

/* ------------------------------------------------------------- BOM */
export function BOMTable({ projectId, editable }: { projectId?: number; editable: boolean }) {
  const session = useSession()
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const [status, setStatus] = useState('')
  const [late, setLate] = useState(false)
  const [form, setForm] = useState<any | null>(null)
  const q = useQuery({ queryKey: ['bom', projectId, status, late], queryFn: () => api.get('/api/bom-items', { project_id: projectId, status, late, page_size: 200 }) })
  const del = useMutation({
    mutationFn: (id: number) => api.del(`/api/bom-items/${id}`),
    onSuccess: () => { toast('BOM item removed'); invalidate(qc) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const fin = session.permissions.finance
  return (
    <div className="card">
      <div className="card-head"><div><h3>Bill of materials</h3><p>Items, specifications, quantities, rates and procurement status.</p></div>
        <div className="row">
          <Select value={status} onChange={setStatus} options={opts(PROCUREMENT_STATUSES)} placeholder="All statuses" className="sm" aria-label="Filter status" />
          <label className="checkbox small"><input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> Late only</label>
          {editable && projectId && <button className="btn primary sm" onClick={() => setForm({})}><Plus size={14} /> Add item</button>}
        </div>
      </div>
      <QueryState q={q}>
        {q.data?.items.length === 0 ? <Empty title="No BOM items" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Item</th><th>Specification</th><th className="num">Qty</th><th className="num">Received</th>{fin && <><th className="num">Est. rate</th><th className="num">Actual rate</th><th className="num">Est. total</th></>}<th>Supplier</th><th>Required</th><th>Status</th><th /></tr></thead>
            <tbody>{q.data?.items.map((b: any) => (
              <tr key={b.id} className={b.is_late ? 'overdue' : ''}>
                <td><b>{b.item_name}</b>{b.description && <div className="small muted">{b.description}</div>}{b.remarks && <div className="small muted">{b.remarks}</div>}</td>
                <td className="small">{b.specification ?? '—'}</td>
                <td className="num">{num(b.quantity, 3)} {b.unit}</td>
                <td className="num">{num(b.received_quantity, 3)}</td>
                {fin && <><td className="num">{money(b.estimated_rate)}</td><td className="num">{money(b.actual_rate)}</td><td className="num">{money(b.estimated_total)}</td></>}
                <td>{b.supplier_name ?? '—'}</td>
                <td className="nowrap">{date(b.required_date)}{b.is_late && <div><Badge text="Late" kind="danger" /></div>}</td>
                <td><Badge value={b.procurement_status} /></td>
                <td className="actions">{editable && <>
                  <button className="btn xs ghost" aria-label="Edit" onClick={() => setForm(b)}><Pencil size={14} /></button>
                  <button className="btn xs ghost" aria-label="Delete" onClick={async () => { if (await confirm({ title: 'Remove BOM item?', message: `${b.item_name} will be removed. Items on an active supplier PO cannot be removed.`, danger: true, confirmText: 'Remove' })) del.mutate(b.id) }}><Trash2 size={14} /></button>
                </>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </QueryState>
      {form && projectId && <BOMForm projectId={projectId} item={form.id ? form : null} onClose={() => setForm(null)} />}
    </div>
  )
}

function BOMForm({ projectId, item, onClose }: { projectId: number; item: any | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const suppliers = useSupplierOptions()
  const f = useForm({
    item_name: item?.item_name ?? '', description: item?.description ?? '', specification: item?.specification ?? '', quantity: item?.quantity ?? '',
    unit: item?.unit ?? 'nos', estimated_rate: item?.estimated_rate ?? '', actual_rate: item?.actual_rate ?? '', supplier_id: item?.supplier_id ?? '',
    required_date: item?.required_date ?? '', procurement_status: item?.procurement_status ?? 'pending', received_quantity: item?.received_quantity ?? '0', remarks: item?.remarks ?? '',
  })
  const v = f.values
  const recvErr = Number(v.received_quantity) > Number(v.quantity) ? 'Cannot exceed quantity' : undefined
  const save = () => f.submit(async () => {
    const body = clean({ ...v, supplier_id: Number(v.supplier_id) || null })
    if (item) await api.patch(`/api/bom-items/${item.id}`, body)
    else await api.post('/api/bom-items', { ...body, project_id: projectId })
    toast(item ? 'BOM item updated' : 'BOM item added')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  const e = f.errors
  return (
    <Modal title={item ? 'Edit BOM item' : 'Add BOM item'} onClose={onClose} size="lg"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !v.item_name || !(Number(v.quantity) > 0) || !!recvErr} onClick={save}>{f.submitting ? 'Saving…' : 'Save'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <div className="form-grid">
          <Field label="Item name" required error={e.item_name} className="span-2"><input className="input" value={v.item_name} onChange={(x) => f.set('item_name', x.target.value)} /></Field>
          <Field label="Description" className="span-2"><input className="input" value={v.description} onChange={(x) => f.set('description', x.target.value)} /></Field>
          <Field label="Material specification" className="span-2"><textarea className="input" style={{ minHeight: 56 }} value={v.specification} onChange={(x) => f.set('specification', x.target.value)} /></Field>
          <Field label="Quantity" required error={e.quantity}><input type="number" min={0} step="0.001" className="input" value={v.quantity} onChange={(x) => f.set('quantity', x.target.value)} /></Field>
          <Field label="Unit" required><input className="input" value={v.unit} onChange={(x) => f.set('unit', x.target.value)} /></Field>
          <Field label="Estimated rate" error={e.estimated_rate}><input type="number" min={0} step="0.01" className="input" value={v.estimated_rate} onChange={(x) => f.set('estimated_rate', x.target.value)} /></Field>
          <Field label="Actual rate" hint="Filled automatically from linked supplier PO lines"><input type="number" min={0} step="0.01" className="input" value={v.actual_rate} onChange={(x) => f.set('actual_rate', x.target.value)} /></Field>
          <Field label="Supplier"><Select value={v.supplier_id} onChange={(x) => f.set('supplier_id', x)} options={suppliers.data ?? []} placeholder="Not selected" /></Field>
          <Field label="Required date"><input type="date" className="input" value={v.required_date} onChange={(x) => f.set('required_date', x.target.value)} /></Field>
          <Field label="Procurement status"><Select value={v.procurement_status} onChange={(x) => f.set('procurement_status', x)} options={opts(PROCUREMENT_STATUSES)} /></Field>
          <Field label="Received quantity" error={recvErr}><input type="number" min={0} step="0.001" className="input" value={v.received_quantity} onChange={(x) => f.set('received_quantity', x.target.value)} /></Field>
          <Field label="Remarks" className="span-2"><textarea className="input" style={{ minHeight: 56 }} value={v.remarks} onChange={(x) => f.set('remarks', x.target.value)} /></Field>
        </div>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------- supplier POs */
export function SupplierPOTable({ projectId, editable }: { projectId?: number; editable: boolean }) {
  const [status, setStatus] = useState('')
  const [late, setLate] = useState(false)
  const [missing, setMissing] = useState(false)
  const [form, setForm] = useState<any | null>(null)
  const [receive, setReceive] = useState<any | null>(null)
  const [pay, setPay] = useState<any | null>(null)
  const [attach, setAttach] = useState<any | null>(null)
  const q = useQuery({ queryKey: ['spos', projectId, status, late, missing], queryFn: () => api.get('/api/supplier-pos', { project_id: projectId, status, late, missing_document: missing, page_size: 100 }) })
  return (
    <div className="card">
      <div className="card-head"><div><h3>Supplier purchase orders</h3><p>Linked to BOM items. Payments here are money paid out and never mixed with client receipts.</p></div>
        <div className="row">
          <Select value={status} onChange={setStatus} options={opts(SPO_STATUSES)} placeholder="All statuses" className="sm" aria-label="Filter status" />
          <label className="checkbox small"><input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> Late</label>
          <label className="checkbox small"><input type="checkbox" checked={missing} onChange={(e) => setMissing(e.target.checked)} /> Missing document</label>
          {editable && projectId && <button className="btn primary sm" onClick={() => setForm({})}><Plus size={14} /> New supplier PO</button>}
        </div>
      </div>
      <QueryState q={q}>
        {q.data?.items.length === 0 ? <Empty title="No supplier POs" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>PO</th><th>Supplier</th><th>PO date</th><th>Delivery</th><th>Status</th><th className="num">Total</th><th className="num">Paid / balance</th><th>Document</th><th /></tr></thead>
            <tbody>{q.data?.items.map((p: any) => (
              <tr key={p.id} className={p.is_late ? 'overdue' : ''}>
                <td className="mono"><b>{p.po_number}</b><div className="small muted" style={{ fontFamily: 'inherit' }}>{p.items.length} line(s)</div></td>
                <td>{p.supplier_name}</td>
                <td>{date(p.po_date)}</td>
                <td className="nowrap">{date(p.delivery_date)}{p.is_late && <div><Badge text="Late" kind="danger" /></div>}{p.actual_delivery_date && <div className="small muted">Received {date(p.actual_delivery_date)}</div>}</td>
                <td><Badge value={p.status} /></td>
                <td className="num"><b>{money(p.total_amount, p.currency)}</b><div className="small muted">tax {money(p.tax_amount, p.currency)}</div></td>
                <td className="num">{money(p.paid_amount, p.currency)}<div className="small muted">bal {money(p.balance_due, p.currency)}</div></td>
                <td>{p.document_id ? <DocLink doc={{ id: p.document_id, title: p.po_number, extension: 'pdf', original_filename: p.po_number }} /> : <Badge text="Missing" kind="warn" />}</td>
                <td className="actions">{editable && <>
                  {!['cancelled', 'draft'].includes(p.status) && <button className="btn xs" title="Record receipt" onClick={() => setReceive(p)}><PackageCheck size={13} /> Receive</button>}
                  {p.status !== 'cancelled' && Number(p.balance_due) > 0 && <button className="btn xs" title="Record supplier payment" onClick={() => setPay(p)}><Wallet size={13} /> Pay</button>}
                  <button className="btn xs ghost" title="Attach document" aria-label="Attach document" onClick={() => setAttach(p)}><Paperclip size={13} /></button>
                  {p.status !== 'cancelled' && <button className="btn xs ghost" aria-label="Edit" onClick={() => setForm(p)}><Pencil size={14} /></button>}
                </>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </QueryState>
      {form && <SupplierPOForm projectId={form.project_id ?? projectId!} po={form.id ? form : null} onClose={() => setForm(null)} />}
      {receive && <ReceiveModal po={receive} onClose={() => setReceive(null)} />}
      {pay && <SupplierPaymentModal po={pay} onClose={() => setPay(null)} />}
      {attach && <AttachSPODoc po={attach} onClose={() => setAttach(null)} />}
    </div>
  )
}

function AttachSPODoc({ po, onClose }: { po: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  return (
    <UploadModal projectId={po.project_id} category="supplier_po" links={{ supplier_po_id: po.id, supplier_id: po.supplier_id }} title={`Attach document to ${po.po_number}`}
      onClose={onClose}
      onUploaded={async (r) => {
        if (!po.document_id) {
          try {
            await api.patch(`/api/supplier-pos/${po.id}`, { document_id: r.document.id })
          } catch (e) {
            toast(errorMessage(e), 'error')
          }
        }
        invalidate(qc)
      }} />
  )
}

interface POLine { bom_item_id: string; description: string; quantity: string; unit: string; unit_price: string; tax_rate: string; received_quantity: string }

function SupplierPOForm({ projectId, po, onClose }: { projectId: number; po: any | null; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const suppliers = useSupplierOptions()
  const bom = useQuery({ queryKey: ['bom', projectId, '', false], queryFn: () => api.get('/api/bom-items', { project_id: projectId, page_size: 200 }) })
  const f = useForm({
    supplier_id: po?.supplier_id ?? '', po_number: po?.po_number ?? '', po_date: po?.po_date ?? todayIso(), delivery_date: po?.delivery_date ?? '',
    actual_delivery_date: po?.actual_delivery_date ?? '', currency: po?.currency ?? 'INR', payment_terms: po?.payment_terms ?? '', status: po?.status ?? 'ordered', notes: po?.notes ?? '',
    items: (po?.items ?? [{ bom_item_id: '', description: '', quantity: '', unit: 'nos', unit_price: '', tax_rate: '18', received_quantity: '0' }]).map((i: any) => ({
      bom_item_id: i.bom_item_id ? String(i.bom_item_id) : '', description: i.description, quantity: String(i.quantity), unit: i.unit, unit_price: String(i.unit_price), tax_rate: String(i.tax_rate), received_quantity: String(i.received_quantity ?? 0),
    })) as POLine[],
  })
  const v = f.values
  const bomItems = (bom.data?.items ?? []) as any[]
  const setLine = (i: number, patch: Partial<POLine>) => f.set('items', v.items.map((l, j) => (j === i ? { ...l, ...patch } : l)))
  const subtotal = v.items.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0), 0)
  const tax = v.items.reduce((s, l) => s + (Number(l.quantity) || 0) * (Number(l.unit_price) || 0) * (Number(l.tax_rate) || 0) / 100, 0)
  const linesValid = v.items.length > 0 && v.items.every((l) => l.description && Number(l.quantity) > 0 && l.unit_price !== '' && Number(l.received_quantity) <= Number(l.quantity))
  const save = () => f.submit(async () => {
    const items = v.items.map((l) => ({ ...l, bom_item_id: Number(l.bom_item_id) || null }))
    const body = { ...clean({ ...v, items: undefined }), supplier_id: Number(v.supplier_id), items }
    if (po) await api.patch(`/api/supplier-pos/${po.id}`, body)
    else await api.post('/api/supplier-pos', { ...body, project_id: projectId })
    toast(po ? 'Supplier PO updated' : 'Supplier PO created')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  return (
    <Modal title={po ? `Edit ${po.po_number}` : 'New supplier PO'} onClose={onClose} size="xl"
      footer={<><span className="muted" style={{ marginRight: 'auto' }}>Subtotal {money(subtotal, v.currency)} · Tax {money(tax, v.currency)} · <b>Total {money(subtotal + tax, v.currency)}</b> (calculated on server)</span>
        <button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !v.supplier_id || !v.po_number || !linesValid} onClick={save}>{f.submitting ? 'Saving…' : 'Save PO'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        {suppliers.data?.length === 0 && <Alert kind="warn">Add a supplier first (BOM Purchase Orders → Suppliers).</Alert>}
        <div className="form-grid">
          <Field label="Supplier" required><Select value={v.supplier_id} onChange={(x) => f.set('supplier_id', x)} options={suppliers.data ?? []} placeholder="Select supplier" disabled={!!po} /></Field>
          <Field label="Supplier PO number" required error={f.errors.po_number}><input className="input mono" value={v.po_number} onChange={(x) => f.set('po_number', x.target.value)} /></Field>
          <Field label="PO date"><input type="date" className="input" value={v.po_date} onChange={(x) => f.set('po_date', x.target.value)} /></Field>
          <Field label="Delivery date"><input type="date" className="input" value={v.delivery_date} onChange={(x) => f.set('delivery_date', x.target.value)} /></Field>
          <Field label="Status"><Select value={v.status} onChange={(x) => f.set('status', x)} options={opts(SPO_STATUSES)} /></Field>
          <Field label="Currency"><Select value={v.currency} onChange={(x) => f.set('currency', x)} options={CURRENCIES.map((c) => ({ value: c, label: c }))} /></Field>
          <Field label="Payment terms" className="span-2"><input className="input" value={v.payment_terms} onChange={(x) => f.set('payment_terms', x.target.value)} /></Field>
        </div>
        <div className="section-title">Line items</div>
        <div className="table-wrap"><table className="table">
          <thead><tr><th style={{ minWidth: 180 }}>BOM item</th><th style={{ minWidth: 180 }}>Description</th><th>Qty</th><th>Unit</th><th>Unit price</th><th>Tax %</th><th>Received</th><th /></tr></thead>
          <tbody>{v.items.map((l, i) => (
            <tr key={i}>
              <td><Select className="sm" value={l.bom_item_id} aria-label="BOM item" onChange={(x) => {
                const b = bomItems.find((bi) => String(bi.id) === x)
                setLine(i, b ? { bom_item_id: x, description: l.description || b.item_name, quantity: l.quantity || String(b.quantity), unit: b.unit, unit_price: l.unit_price || (b.estimated_rate ?? '') } : { bom_item_id: x })
              }} options={bomItems.map((b) => ({ value: b.id, label: b.item_name }))} placeholder="Not linked" /></td>
              <td><input className="input sm" value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} aria-label="Description" /></td>
              <td><input className="input sm" type="number" min={0} step="0.001" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} style={{ width: 80 }} aria-label="Quantity" /></td>
              <td><input className="input sm" value={l.unit} onChange={(e) => setLine(i, { unit: e.target.value })} style={{ width: 60 }} aria-label="Unit" /></td>
              <td><input className="input sm" type="number" min={0} step="0.01" value={l.unit_price} onChange={(e) => setLine(i, { unit_price: e.target.value })} style={{ width: 110 }} aria-label="Unit price" /></td>
              <td><input className="input sm" type="number" min={0} max={100} step="0.01" value={l.tax_rate} onChange={(e) => setLine(i, { tax_rate: e.target.value })} style={{ width: 70 }} aria-label="Tax rate" /></td>
              <td><input className={`input sm ${Number(l.received_quantity) > Number(l.quantity) ? 'invalid' : ''}`} type="number" min={0} step="0.001" value={l.received_quantity} onChange={(e) => setLine(i, { received_quantity: e.target.value })} style={{ width: 80 }} aria-label="Received" /></td>
              <td><button className="btn xs ghost" disabled={v.items.length === 1} onClick={() => f.set('items', v.items.filter((_, j) => j !== i))} aria-label="Remove line"><Trash2 size={14} /></button></td>
            </tr>
          ))}</tbody>
        </table></div>
        <div><button className="btn sm" onClick={() => f.set('items', [...v.items, { bom_item_id: '', description: '', quantity: '', unit: 'nos', unit_price: '', tax_rate: '18', received_quantity: '0' }])}><Plus size={14} /> Add line</button></div>
        <Field label="Notes"><textarea className="input" style={{ minHeight: 56 }} value={v.notes} onChange={(x) => f.set('notes', x.target.value)} /></Field>
      </div>
    </Modal>
  )
}

function ReceiveModal({ po, onClose }: { po: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [qty, setQty] = useState<Record<number, string>>(Object.fromEntries(po.items.map((i: any) => [i.id, String(i.received_quantity)])))
  const m = useMutation({
    mutationFn: () => api.post(`/api/supplier-pos/${po.id}/receive`, po.items.map((i: any) => ({ item_id: i.id, received_quantity: qty[i.id] || '0' }))),
    onSuccess: () => { toast('Receipt recorded; BOM status updated'); invalidate(qc); onClose() },
  })
  const invalid = po.items.some((i: any) => Number(qty[i.id]) > Number(i.quantity) || Number(qty[i.id]) < 0)
  return (
    <Modal title={<><Truck size={18} style={{ verticalAlign: -3 }} /> Record receipt · {po.po_number}</>} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={m.isPending || invalid} onClick={() => m.mutate()}>{m.isPending ? 'Saving…' : 'Save receipt'}</button></>}>
      {m.error && <Alert kind="danger">{errorMessage(m.error)}</Alert>}
      <table className="table">
        <thead><tr><th>Item</th><th className="num">Ordered</th><th>Total received</th></tr></thead>
        <tbody>{po.items.map((i: any) => (
          <tr key={i.id}><td>{i.description}</td><td className="num">{num(i.quantity, 3)} {i.unit}</td>
            <td><input className={`input sm ${Number(qty[i.id]) > Number(i.quantity) ? 'invalid' : ''}`} type="number" min={0} max={i.quantity} step="0.001" value={qty[i.id]} onChange={(e) => setQty((s) => ({ ...s, [i.id]: e.target.value }))} aria-label="Received quantity" /></td></tr>
        ))}</tbody>
      </table>
      <p className="small muted mt-8">PO status becomes Partially received or Received automatically.</p>
    </Modal>
  )
}

function SupplierPaymentModal({ po, onClose }: { po: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const f = useForm({ amount: po.balance_due, payment_date: todayIso(), method: 'bank_transfer', reference: '', notes: '' })
  const v = f.values
  const over = Number(v.amount) > Number(po.balance_due)
  const save = () => f.submit(async () => {
    await api.post('/api/supplier-payments', clean({ ...v, supplier_po_id: po.id }))
    toast('Supplier payment recorded')
    invalidate(qc)
    onClose()
  }).catch(() => {})
  return (
    <Modal title={`Pay supplier · ${po.po_number}`} onClose={onClose} size="sm"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={f.submitting || !(Number(v.amount) > 0) || over} onClick={save}>{f.submitting ? 'Saving…' : 'Record payment'}</button></>}>
      <div className="form">
        <Alert kind="info">This is a payment <b>to the supplier</b>. It affects procurement cost only, never client receivables.</Alert>
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <p className="small">PO total {money(po.total_amount, po.currency)} · already paid {money(po.paid_amount, po.currency)} · balance <b>{money(po.balance_due, po.currency)}</b></p>
        <Field label="Amount" required error={over ? 'Exceeds PO balance' : f.errors.amount}><input type="number" min={0.01} step="0.01" className="input" value={v.amount} onChange={(x) => f.set('amount', x.target.value)} /></Field>
        <Field label="Payment date" required><input type="date" className="input" max={todayIso()} value={v.payment_date} onChange={(x) => f.set('payment_date', x.target.value)} /></Field>
        <Field label="Method"><Select value={v.method} onChange={(x) => f.set('method', x)} options={opts(PAYMENT_METHODS)} /></Field>
        <Field label="Reference" hint="Must be unique"><input className="input mono" value={v.reference} onChange={(x) => f.set('reference', x.target.value)} /></Field>
        <Field label="Notes"><textarea className="input" style={{ minHeight: 56 }} value={v.notes} onChange={(x) => f.set('notes', x.target.value)} /></Field>
      </div>
    </Modal>
  )
}

export function SupplierPaymentsTable({ projectId, editable }: { projectId?: number; editable: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const q = useQuery({ queryKey: ['supplier-payments', projectId], queryFn: () => api.get('/api/supplier-payments', { project_id: projectId, page_size: 100 }) })
  const m = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) => api.post(`/api/supplier-payments/${id}/status`, { status }),
    onSuccess: () => { toast('Supplier payment updated'); invalidate(qc) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  return (
    <div className="card">
      <div className="card-head"><div><h3>Supplier payments (outgoing)</h3><p>Tracked separately from client payments to prevent double counting.</p></div></div>
      <QueryState q={q}>
        {q.data?.items.length === 0 ? <Empty title="No supplier payments" /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Date</th><th>Supplier PO</th><th>Method</th><th>Reference</th><th>Status</th><th className="num">Amount</th><th /></tr></thead>
            <tbody>{q.data?.items.map((p: any) => (
              <tr key={p.id} className={p.status === 'reversed' ? 'muted-row' : ''}>
                <td>{date(p.payment_date)}</td><td>#{p.supplier_po_id}</td><td>{label(p.method)}</td><td className="mono">{p.reference ?? '—'}</td>
                <td><Badge value={p.status} /></td><td className="num">{money(p.amount)}</td>
                <td className="actions">{editable && p.status !== 'reversed' && <>
                  {p.status === 'recorded' && <button className="btn xs" onClick={() => m.mutate({ id: p.id, status: 'verified' })}>Verify</button>}
                  <button className="btn xs ghost" onClick={async () => { if (await confirm({ title: 'Reverse supplier payment?', message: 'The amount will no longer count as paid. The record is kept.', danger: true, confirmText: 'Reverse' })) m.mutate({ id: p.id, status: 'reversed' }) }}>Reverse</button>
                </>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </QueryState>
    </div>
  )
}

export function ProjectProcurementPanel({ projectId, currency, editable }: { projectId: number; currency: string; editable: boolean }) {
  const session = useSession()
  const s = useQuery({ queryKey: ['procurement', projectId], queryFn: () => api.get(`/api/projects/${projectId}/procurement`), enabled: session.permissions.finance })
  return (
    <div className="stack">
      {session.permissions.finance && <QueryState q={s}>{s.data && <ProcurementSummary s={s.data} currency={currency} />}</QueryState>}
      <BOMTable projectId={projectId} editable={editable} />
      {session.permissions.finance ? <>
        <SupplierPOTable projectId={projectId} editable={editable} />
        <SupplierPaymentsTable projectId={projectId} editable={editable} />
      </> : <Alert kind="info"><AlertTriangle size={14} /> Supplier purchase orders and costs are visible to Admins and Project Managers.</Alert>}
    </div>
  )
}
