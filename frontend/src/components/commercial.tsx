import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, FilePlus2, GitCompare, History, Pencil, Plus, Star, Trash2, UploadCloud } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { CURRENCIES, date, dateTime, label, money } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, QueryState, Select, Spinner, clean, errorMessage, useForm, useToast } from './ui'
import { DocLink, FilePicker } from './documents'

type Kind = 'quotation' | 'client_po'
interface LineItem { description: string; quantity?: string; unit?: string; unit_price?: string; amount?: string }
type Extraction = { fields: Record<string, { value: any; confidence: 'high' | 'medium' | 'low'; source: string }>; line_items: LineItem[]; warnings: string[]; method?: string }

/* ------------------------------------------------------------- line items */
export function LineItemsEditor({ items, onChange }: { items: LineItem[]; onChange: (i: LineItem[]) => void }) {
  const upd = (i: number, k: keyof LineItem, v: string) => onChange(items.map((it, j) => (j === i ? { ...it, [k]: v } : it)))
  return (
    <div>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>Description</th><th style={{ width: 90 }}>Qty</th><th style={{ width: 80 }}>Unit</th><th style={{ width: 120 }}>Unit price</th><th style={{ width: 130 }}>Amount</th><th /></tr></thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i}>
              <td><input className="input sm" value={it.description} onChange={(e) => upd(i, 'description', e.target.value)} aria-label="Description" /></td>
              <td><input className="input sm" type="number" min={0} value={it.quantity ?? ''} onChange={(e) => upd(i, 'quantity', e.target.value)} aria-label="Quantity" /></td>
              <td><input className="input sm" value={it.unit ?? ''} onChange={(e) => upd(i, 'unit', e.target.value)} aria-label="Unit" /></td>
              <td><input className="input sm" type="number" min={0} step="0.01" value={it.unit_price ?? ''} onChange={(e) => upd(i, 'unit_price', e.target.value)} aria-label="Unit price" /></td>
              <td><input className="input sm" type="number" min={0} step="0.01" value={it.amount ?? ''} placeholder={it.quantity && it.unit_price ? String(+it.quantity * +it.unit_price) : ''}
                onChange={(e) => upd(i, 'amount', e.target.value)} aria-label="Amount" /></td>
              <td><button type="button" className="btn xs ghost" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label="Remove line"><Trash2 size={14} /></button></td>
            </tr>
          ))}
        </tbody>
      </table></div>
      <button type="button" className="btn sm mt-8" onClick={() => onChange([...items, { description: '' }])}><Plus size={14} /> Add line</button>
    </div>
  )
}

function Conf({ ex, k }: { ex?: Extraction | null; k: string }) {
  const f = ex?.fields?.[k]
  if (!f) return null
  return <span className={`conf ${f.confidence}`} title={`Extracted from: ${f.source}`}>{f.confidence === 'high' ? 'extracted' : 'verify'}</span>
}

/* ------------------------------------------------------------- shared commercial form */
function CommercialForm({ kind, projectId, mode, initial, quotationId, onClose }: {
  kind: Kind; projectId: number; mode: 'create' | 'revision' | 'edit'; initial?: any; quotationId?: number; onClose: () => void
}) {
  const qc = useQueryClient()
  const toast = useToast()
  const [step, setStep] = useState<'upload' | 'form'>(mode === 'edit' ? 'form' : 'upload')
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [documentId, setDocumentId] = useState<number | null>(initial?.document_id ?? null)
  const [extraction, setExtraction] = useState<Extraction | null>(initial?.extraction ?? null)
  const approvedQ = useQuery({
    queryKey: ['quotations', projectId], queryFn: () => api.get('/api/quotations', { project_id: projectId }), enabled: kind === 'client_po',
  })
  const isPO = kind === 'client_po'
  const f = useForm({
    number: (isPO ? initial?.po_number : initial?.quotation_number) ?? '',
    title: initial?.title ?? '',
    doc_date: (isPO ? initial?.issue_date : initial?.quotation_date) ?? '',
    validity_date: initial?.validity_date ?? '',
    subtotal: (isPO ? initial?.po_value : initial?.subtotal) ?? '',
    tax_amount: initial?.tax_amount ?? '',
    total: (isPO ? initial?.total_value : initial?.total_amount) ?? '',
    currency: initial?.currency ?? 'INR',
    payment_terms: initial?.payment_terms ?? '',
    delivery_terms: initial?.delivery_terms ?? '',
    delivery_date: initial?.delivery_date ?? '',
    scope: initial?.scope ?? '',
    notes: initial?.notes ?? '',
    quotation_version_id: initial?.quotation_version_id ?? '',
    line_items: (initial?.line_items ?? []) as LineItem[],
    verified: !!initial?.extraction_verified,
  })
  const v = f.values

  const applyExtraction = (ex: Extraction) => {
    const g = (k: string) => ex.fields[k]?.value ?? ''
    f.setValues((s) => ({
      ...s,
      number: s.number || (mode === 'create' ? g('number') : s.number),
      doc_date: g('date') || s.doc_date, validity_date: g('validity_date') || s.validity_date,
      subtotal: g('subtotal') || s.subtotal, tax_amount: g('tax_amount') || s.tax_amount, total: g('total_amount') || s.total,
      currency: g('currency') || s.currency, payment_terms: g('payment_terms') || s.payment_terms, delivery_terms: g('delivery_terms') || s.delivery_terms,
      delivery_date: g('delivery_date') || s.delivery_date,
      line_items: ex.line_items.length ? ex.line_items : s.line_items, verified: false,
    }))
  }

  const doUpload = async () => {
    if (!file) { setStep('form'); return }
    setUploading(true)
    setUploadError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('project_id', String(projectId))
      form.append('category', kind)
      const r = await api.upload('/api/documents', form)
      setDocumentId(r.document.id)
      if (r.extraction) {
        setExtraction(r.extraction)
        applyExtraction(r.extraction)
      }
      qc.invalidateQueries({ queryKey: ['documents'] })
      setStep('form')
    } catch (e) {
      setUploadError(errorMessage(e))
    } finally {
      setUploading(false)
    }
  }

  const sub = Number(v.subtotal), tax = Number(v.tax_amount), tot = Number(v.total)
  const mismatch = v.subtotal !== '' && v.tax_amount !== '' && v.total !== '' && Math.abs(sub + tax - tot) > 1
  const needsVerify = !!extraction && Object.keys(extraction.fields).length > 0
  const dateErr = !isPO && v.doc_date && v.validity_date && v.validity_date < v.doc_date ? 'Validity date cannot be before quotation date' : undefined

  const save = () => f.submit(async () => {
    const items = v.line_items.filter((i) => i.description.trim()).map((i) => clean(i))
    const common = clean({
      currency: v.currency, payment_terms: v.payment_terms, delivery_terms: v.delivery_terms, delivery_date: v.delivery_date, scope: v.scope,
      tax_amount: v.tax_amount, line_items: items, extraction_verified: needsVerify ? v.verified : undefined,
    })
    if (isPO) {
      const body = { ...common, po_number: v.number, issue_date: v.doc_date || null, po_value: v.subtotal || null, total_value: v.total || null,
        quotation_version_id: Number(v.quotation_version_id) || null, document_id: documentId }
      if (mode === 'edit') await api.patch(`/api/client-pos/${initial.id}`, body)
      else await api.post('/api/client-pos', { ...body, project_id: projectId })
      toast(mode === 'edit' ? 'Client PO updated' : 'Client PO recorded')
    } else {
      const body = { ...common, quotation_date: v.doc_date || null, validity_date: v.validity_date || null, subtotal: v.subtotal || null,
        total_amount: v.total || null, notes: v.notes || null }
      if (mode === 'create') await api.post('/api/quotations', { ...body, project_id: projectId, quotation_number: v.number, title: v.title || null, document_id: documentId })
      else if (mode === 'revision') await api.post(`/api/quotations/${quotationId}/versions`, body, { document_id: documentId ?? undefined })
      else await api.patch(`/api/quotation-versions/${initial.id}`, body)
      toast(mode === 'revision' ? 'New revision added; earlier open revisions are marked superseded' : 'Quotation saved')
    }
    qc.invalidateQueries({ queryKey: ['quotations'] })
    qc.invalidateQueries({ queryKey: ['client-pos'] })
    qc.invalidateQueries({ queryKey: ['client-po'] })
    qc.invalidateQueries({ queryKey: ['project'] })
    onClose()
  }).catch(() => {})

  const title = isPO ? (mode === 'edit' ? `Edit PO ${initial.po_number}` : 'Record client PO')
    : mode === 'create' ? 'New quotation' : mode === 'revision' ? 'New quotation revision' : `Edit revision R${initial.revision_number}`
  const e = f.errors
  const uncertain = (k: string) => (extraction?.fields?.[k] && extraction.fields[k].confidence !== 'high' ? 'uncertain' : '')
  const approvedVersions = ((approvedQ.data?.items ?? []) as any[]).flatMap((q) => q.versions.filter((x: any) => x.status === 'approved').map((x: any) => ({ value: x.id, label: `${q.quotation_number} R${x.revision_number} · ${money(x.total_amount, x.currency)}` })))

  if (step === 'upload')
    return (
      <Modal title={title} onClose={onClose}
        footer={<><button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={() => setStep('form')}>Skip, enter manually</button>
          <button className="btn primary" disabled={!file || uploading} onClick={doUpload}>{uploading ? 'Uploading & reading…' : 'Upload & extract'}</button></>}>
        <div className="form">
          <p className="muted">Upload the {isPO ? 'client purchase order' : 'quotation'} (PDF or DOCX recommended). The original file is stored securely and the system will try to read key details for you to verify.</p>
          {uploadError && <Alert kind="danger">{uploadError}</Alert>}
          <FilePicker file={file} onFile={setFile} />
          {uploading && <div className="row"><Spinner /> <span className="muted">Reading document…</span></div>}
        </div>
      </Modal>
    )

  return (
    <Modal title={title} onClose={onClose} size="xl"
      footer={<><button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={f.submitting || !v.number && mode !== 'revision' && mode !== 'edit' || (needsVerify && !v.verified) || !!dateErr} onClick={save}>{f.submitting ? 'Saving…' : 'Save'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        {documentId && <Alert kind="ok">Document attached (#{documentId}). The original file is preserved.</Alert>}
        {extraction && (
          <Alert kind="warn">
            <b>Automatically extracted values need your verification.</b> Fields marked <span className="conf medium">verify</span> are uncertain; <span className="conf high">extracted</span> values were found with consistent totals but may still be wrong.
            {extraction.method && extraction.method !== 'pdf_text_layer' && extraction.method !== 'docx' && <> Extraction note: {label(extraction.method)}.</>}
            {extraction.warnings.slice(1).map((w) => <div key={w}>• {w}</div>)}
            {Object.keys(extraction.fields).length === 0 && <div>No fields could be read. Enter the details manually.</div>}
          </Alert>
        )}
        <div className="form-grid">
          {(mode === 'create' || (isPO && mode === 'edit')) && (
            <Field label={<>{isPO ? 'Client PO number' : 'Quotation number'}<Conf ex={extraction} k="number" /></>} required error={e.po_number || e.quotation_number}>
              <input className={`input mono ${uncertain('number')}`} value={v.number} onChange={(x) => f.set('number', x.target.value)} />
            </Field>
          )}
          {!isPO && mode === 'create' && <Field label="Title"><input className="input" value={v.title} onChange={(x) => f.set('title', x.target.value)} /></Field>}
          <Field label={<>{isPO ? 'Issue date' : 'Quotation date'}<Conf ex={extraction} k="date" /></>} error={e.issue_date || e.quotation_date}>
            <input type="date" className={`input ${uncertain('date')}`} value={v.doc_date} onChange={(x) => f.set('doc_date', x.target.value)} />
          </Field>
          {!isPO && <Field label={<>Validity date<Conf ex={extraction} k="validity_date" /></>} error={e.validity_date || dateErr}>
            <input type="date" className={`input ${uncertain('validity_date')}`} value={v.validity_date} onChange={(x) => f.set('validity_date', x.target.value)} />
          </Field>}
          {isPO && <Field label="Compare against quotation" hint="Defaults to the project's currently approved quotation">
            <Select value={v.quotation_version_id} onChange={(x) => f.set('quotation_version_id', x)} options={approvedVersions} placeholder="Current approved quotation" />
          </Field>}
          <Field label={<>{isPO ? 'PO value (pre-tax)' : 'Subtotal'}<Conf ex={extraction} k="subtotal" /></>} error={e.po_value || e.subtotal}>
            <input type="number" min={0} step="0.01" className={`input ${uncertain('subtotal')}`} value={v.subtotal} onChange={(x) => f.set('subtotal', x.target.value)} />
          </Field>
          <Field label={<>Taxes<Conf ex={extraction} k="tax_amount" /></>} error={e.tax_amount}>
            <input type="number" min={0} step="0.01" className={`input ${uncertain('tax_amount')}`} value={v.tax_amount} onChange={(x) => f.set('tax_amount', x.target.value)} />
          </Field>
          <Field label={<>{isPO ? 'Total approved value' : 'Total amount'}<Conf ex={extraction} k="total_amount" /></>} error={e.total_value || e.total_amount || (mismatch ? 'Subtotal + taxes does not equal the total' : undefined)}>
            <input type="number" min={0} step="0.01" className={`input ${uncertain('total_amount')} ${mismatch ? 'invalid' : ''}`} value={v.total} onChange={(x) => f.set('total', x.target.value)} />
          </Field>
          <Field label={<>Currency<Conf ex={extraction} k="currency" /></>}><Select value={v.currency} onChange={(x) => f.set('currency', x)} options={CURRENCIES.map((c) => ({ value: c, label: c }))} /></Field>
          <Field label={<>Delivery date<Conf ex={extraction} k="delivery_date" /></>}><input type="date" className={`input ${uncertain('delivery_date')}`} value={v.delivery_date} onChange={(x) => f.set('delivery_date', x.target.value)} /></Field>
          <Field label={<>Payment terms<Conf ex={extraction} k="payment_terms" /></>} className="span-2"><textarea className={`input ${uncertain('payment_terms')}`} style={{ minHeight: 56 }} value={v.payment_terms} onChange={(x) => f.set('payment_terms', x.target.value)} /></Field>
          <Field label={<>Delivery terms<Conf ex={extraction} k="delivery_terms" /></>} className="span-2"><textarea className={`input ${uncertain('delivery_terms')}`} style={{ minHeight: 56 }} value={v.delivery_terms} onChange={(x) => f.set('delivery_terms', x.target.value)} /></Field>
          <Field label="Scope" className="span-2"><textarea className="input" value={v.scope} onChange={(x) => f.set('scope', x.target.value)} /></Field>
          {!isPO && <Field label="Notes" className="span-2"><textarea className="input" style={{ minHeight: 56 }} value={v.notes} onChange={(x) => f.set('notes', x.target.value)} /></Field>}
          <div className="span-2">
            <div className="section-title">Line items {extraction?.line_items?.length ? <span className="conf medium">verify</span> : null}</div>
            <LineItemsEditor items={v.line_items} onChange={(i) => f.set('line_items', i)} />
          </div>
        </div>
        {needsVerify && (
          <label className="checkbox" style={{ padding: 12, border: '1px solid var(--warn)', borderRadius: 8, background: 'var(--warn-soft)' }}>
            <input type="checkbox" checked={v.verified} onChange={(x) => f.set('verified', x.target.checked)} />
            I have checked the extracted values against the original document.
          </label>
        )}
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------- quotations */
export function QuotationsPanel({ projectId, editable }: { projectId: number; editable: boolean }) {
  const q = useQuery({ queryKey: ['quotations', projectId], queryFn: () => api.get('/api/quotations', { project_id: projectId }) })
  const [form, setForm] = useState<{ mode: 'create' | 'revision' | 'edit'; initial?: any; quotationId?: number } | null>(null)
  const [statusFor, setStatusFor] = useState<any | null>(null)
  const items = (q.data?.items ?? []) as any[]
  const approved = items.map((x) => x.approved_version && { q: x, v: x.approved_version }).filter(Boolean)[0] as { q: any; v: any } | undefined
  return (
    <div className="stack">
      {approved ? (
        <div className="card card-body" style={{ borderLeft: '4px solid var(--ok)' }}>
          <div className="row between">
            <div className="row"><Star size={18} color="var(--ok)" fill="var(--ok)" /><div><div className="section-title" style={{ margin: 0 }}>Currently approved quotation</div>
              <h3>{approved.q.quotation_number} · Revision R{approved.v.revision_number}</h3></div></div>
            <div className="right"><div style={{ fontSize: 22, fontWeight: 700 }}>{money(approved.v.total_amount, approved.v.currency)}</div>
              <div className="small muted">Approved {dateTime(approved.v.approved_at)} · valid until {date(approved.v.validity_date)}</div></div>
          </div>
        </div>
      ) : items.length > 0 && <Alert kind="info">No quotation revision is approved yet for this project.</Alert>}
      <div className="card">
        <div className="card-head"><div><h3>Quotations & revisions</h3><p>Older revisions are preserved. Approving a revision supersedes the previously approved one.</p></div>
          {editable && <button className="btn primary sm" onClick={() => setForm({ mode: 'create' })}><FilePlus2 size={14} /> New quotation</button>}</div>
        <QueryState q={q}>
          {items.length === 0 ? <Empty title="No quotations yet" text="Upload a quotation (PDF/DOCX) or enter it manually." /> : items.map((x) => (
            <div key={x.id} style={{ borderBottom: '1px solid var(--border)' }}>
              <div className="row between" style={{ padding: '12px 18px', background: 'var(--steel-50)' }}>
                <div><b className="mono">{x.quotation_number}</b> {x.title && <span className="muted">· {x.title}</span>}</div>
                {editable && <button className="btn sm" onClick={() => setForm({ mode: 'revision', quotationId: x.id, initial: { ...x.latest, document_id: null, extraction: null, extraction_verified: false } })}><Plus size={14} /> New revision</button>}
              </div>
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Rev</th><th>Date</th><th>Valid until</th><th>Status</th><th className="num">Subtotal</th><th className="num">Taxes</th><th className="num">Total</th><th>Terms</th><th>File</th><th /></tr></thead>
                <tbody>{x.versions.map((v: any) => (
                  <tr key={v.id} className={['superseded', 'expired', 'rejected'].includes(v.effective_status) ? 'muted-row' : ''}>
                    <td><b>R{v.revision_number}</b>{v.status === 'approved' && <Star size={12} color="var(--ok)" fill="var(--ok)" style={{ marginLeft: 4 }} />}</td>
                    <td className="nowrap">{date(v.quotation_date)}</td>
                    <td className="nowrap">{date(v.validity_date)}</td>
                    <td><Badge value={v.effective_status} />{v.extraction && !v.extraction_verified && <div><Badge text="Needs verification" kind="warn" /></div>}{v.tax_check && <div className="small" style={{ color: 'var(--danger)' }}><AlertTriangle size={12} /> {v.tax_check}</div>}</td>
                    <td className="num">{money(v.subtotal, v.currency)}</td>
                    <td className="num">{money(v.tax_amount, v.currency)}</td>
                    <td className="num"><b>{money(v.total_amount, v.currency)}</b></td>
                    <td className="small" style={{ maxWidth: 240 }}>{v.payment_terms ?? '—'}</td>
                    <td><DocLink doc={v.document} /></td>
                    <td className="actions">
                      {editable && ['draft', 'submitted', 'rejected'].includes(v.effective_status) && <button className="btn xs ghost" aria-label="Edit" onClick={() => setForm({ mode: 'edit', initial: v })}><Pencil size={14} /></button>}
                      {editable && !['superseded', 'expired'].includes(v.effective_status) && <button className="btn xs" onClick={() => setStatusFor({ ...v, quotation_number: x.quotation_number })}>Status</button>}
                    </td>
                  </tr>
                ))}</tbody>
              </table></div>
            </div>
          ))}
        </QueryState>
      </div>
      {form && <CommercialForm kind="quotation" projectId={projectId} mode={form.mode} initial={form.initial} quotationId={form.quotationId} onClose={() => setForm(null)} />}
      {statusFor && <QuotationStatusModal version={statusFor} onClose={() => setStatusFor(null)} />}
    </div>
  )
}

const Q_NEXT: Record<string, string[]> = { draft: ['submitted', 'approved', 'rejected'], submitted: ['approved', 'rejected', 'draft'], rejected: ['draft'], approved: ['rejected'] }

function QuotationStatusModal({ version, onClose }: { version: any; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const options = Q_NEXT[version.effective_status] ?? []
  const [status, setStatus] = useState(options[0] ?? '')
  const [notes, setNotes] = useState('')
  const m = useMutation({
    mutationFn: () => api.post(`/api/quotation-versions/${version.id}/status`, { status, notes: notes || null }),
    onSuccess: () => { toast(`Quotation marked ${label(status)}`); qc.invalidateQueries({ queryKey: ['quotations'] }); qc.invalidateQueries({ queryKey: ['project'] }); onClose() },
  })
  return (
    <Modal title={`Change status · ${version.quotation_number} R${version.revision_number}`} onClose={onClose} size="sm"
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className={`btn ${status === 'rejected' ? 'danger' : 'primary'}`} disabled={!status || m.isPending} onClick={() => m.mutate()}>{m.isPending ? 'Saving…' : 'Confirm'}</button></>}>
      <div className="form">
        {m.error && <Alert kind="danger">{errorMessage(m.error)}</Alert>}
        <p>Current status: <Badge value={version.effective_status} /></p>
        <Field label="New status"><Select value={status} onChange={setStatus} options={options.map((o) => ({ value: o, label: label(o) }))} /></Field>
        {status === 'approved' && <Alert kind="info">Approving makes this the project's approved quotation. Any previously approved quotation for the project becomes Superseded.</Alert>}
        <Field label="Notes" hint="Recorded in the audit history"><textarea className="input" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}

/* ------------------------------------------------------------- client POs */
export function ClientPOPanel({ projectId, editable }: { projectId: number; editable: boolean }) {
  const q = useQuery({ queryKey: ['client-pos', projectId], queryFn: () => api.get('/api/client-pos', { project_id: projectId }) })
  const [form, setForm] = useState<{ mode: 'create' | 'edit'; initial?: any } | null>(null)
  const [open, setOpen] = useState<number | null>(null)
  const items = (q.data?.items ?? []) as any[]
  return (
    <div className="stack">
      <div className="card">
        <div className="card-head"><div><h3>Client purchase orders</h3><p>Compare each PO against the approved quotation. Discrepancies need manual review before verification.</p></div>
          {editable && <button className="btn primary sm" onClick={() => setForm({ mode: 'create' })}><UploadCloud size={14} /> Record client PO</button>}</div>
        <QueryState q={q}>
          {items.length === 0 ? <Empty title="No client POs" text="Upload the client's purchase order once received." /> : (
            <div className="table-wrap"><table className="table">
              <thead><tr><th>PO number</th><th>Issue date</th><th>Status</th><th className="num">PO value</th><th className="num">Taxes</th><th className="num">Total</th><th>Payment terms</th><th>File</th><th /></tr></thead>
              <tbody>{items.map((po) => (
                <tr key={po.id}>
                  <td className="mono"><b>{po.po_number}</b></td>
                  <td>{date(po.issue_date)}</td>
                  <td><Badge value={po.status} />{po.extraction && !po.extraction_verified && <div><Badge text="Needs verification" kind="warn" /></div>}</td>
                  <td className="num">{money(po.po_value, po.currency)}</td>
                  <td className="num">{money(po.tax_amount, po.currency)}</td>
                  <td className="num"><b>{money(po.total_value, po.currency)}</b></td>
                  <td className="small" style={{ maxWidth: 220 }}>{po.payment_terms ?? '—'}</td>
                  <td><DocLink doc={po.document} /></td>
                  <td className="actions">
                    <button className="btn xs" onClick={() => setOpen(po.id)}><GitCompare size={13} /> Compare & review</button>
                    {editable && !['verified', 'cancelled'].includes(po.status) && <button className="btn xs ghost" aria-label="Edit" onClick={() => setForm({ mode: 'edit', initial: po })}><Pencil size={14} /></button>}
                  </td>
                </tr>
              ))}</tbody>
            </table></div>
          )}
        </QueryState>
      </div>
      {form && <CommercialForm kind="client_po" projectId={projectId} mode={form.mode} initial={form.initial} onClose={() => setForm(null)} />}
      {open && <POReviewModal poId={open} editable={editable} onClose={() => setOpen(null)} />}
    </div>
  )
}

const PO_NEXT: Record<string, string[]> = {
  received: ['under_review', 'verified', 'rejected', 'cancelled'], under_review: ['verified', 'rejected', 'received', 'cancelled'],
  rejected: ['under_review'], verified: ['under_review', 'cancelled'], cancelled: [],
}

function POReviewModal({ poId, editable, onClose }: { poId: number; editable: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['client-po', poId], queryFn: () => api.get(`/api/client-pos/${poId}`) })
  const [status, setStatus] = useState('')
  const [notes, setNotes] = useState('')
  const [ack, setAck] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: () => api.post(`/api/client-pos/${poId}/decision`, { status, review_notes: notes || null }, { acknowledge_discrepancies: ack }),
    onSuccess: () => {
      toast(`PO marked ${label(status)}`)
      ;['client-pos', 'client-po', 'project', 'payments-project'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))
      setStatus(''); setNotes(''); setAck(false); setErr(null)
    },
    onError: (e) => setErr(e instanceof ApiError ? e.message : errorMessage(e)),
  })
  const d = q.data
  const cmp = d?.comparison
  return (
    <Modal title={d ? `Client PO ${d.po.po_number}` : 'Client PO'} onClose={onClose} size="xl" footer={<button className="btn" onClick={onClose}>Close</button>}>
      <QueryState q={q}>
        {d && (
          <div className="stack">
            <div className="row between">
              <div className="row"><Badge value={d.po.status} /> <span className="muted">Issued {date(d.po.issue_date)} · Total {money(d.po.total_value, d.po.currency)}</span></div>
              <DocLink doc={d.po.document} />
            </div>
            <div className="card">
              <div className="card-head"><div><h3><GitCompare size={16} style={{ verticalAlign: -3 }} /> Comparison with approved quotation</h3>
                <p>{cmp.quotation_version_id ? `${cmp.quotation_number} R${cmp.revision_number} · ${cmp.message}` : cmp.message}</p></div>
                {cmp.quotation_version_id && (cmp.discrepancy_count ? <Badge text={`${cmp.discrepancy_count} discrepanc${cmp.discrepancy_count === 1 ? 'y' : 'ies'}`} kind="danger" /> : <Badge text="No discrepancies" kind="ok" />)}
              </div>
              {cmp.rows.length > 0 && (
                <div className="table-wrap"><table className="table">
                  <thead><tr><th>Field</th><th>Approved quotation</th><th>Client PO</th><th>Difference</th><th>Result</th></tr></thead>
                  <tbody>{cmp.rows.map((r: any) => (
                    <tr key={r.field} className={r.status === 'mismatch' ? 'cmp-row-mismatch' : ''}>
                      <td><b>{r.field}</b></td><td className="small pre">{r.quotation ?? '—'}</td><td className="small pre">{r.po ?? '—'}</td>
                      <td className="small">{r.difference ?? (r.similarity != null ? `${Math.round(r.similarity * 100)}% similar` : '')}</td>
                      <td className={`cmp-${r.status}`}>{r.status === 'match' ? <><CheckCircle2 size={14} /> Match</> : r.status === 'mismatch' ? <><AlertTriangle size={14} /> Differs</> : 'Not available'}</td>
                    </tr>
                  ))}</tbody>
                </table></div>
              )}
              {cmp.line_items.length > 0 && (
                <div className="card-body">
                  <div className="section-title">Line items (quantities & prices)</div>
                  <div className="table-wrap"><table className="table">
                    <thead><tr><th>Item</th><th>Result</th><th>Differences</th></tr></thead>
                    <tbody>{cmp.line_items.map((li: any, i: number) => (
                      <tr key={i} className={li.status !== 'match' ? 'cmp-row-mismatch' : ''}>
                        <td>{li.description}{li.po_description && li.po_description !== li.description && <div className="small muted">PO: {li.po_description}</div>}</td>
                        <td className={li.status === 'match' ? 'cmp-match' : 'cmp-mismatch'}>{label(li.status)}</td>
                        <td className="small">{li.differences.map((x: any) => `${label(x.field)}: ${x.quotation} → ${x.po}`).join('; ') || '—'}</td>
                      </tr>
                    ))}</tbody>
                  </table></div>
                </div>
              )}
            </div>
            {editable && (PO_NEXT[d.po.status] ?? []).length > 0 && (
              <div className="card card-body">
                <h3 className="mb-8">Review decision</h3>
                <div className="form">
                  {err && <Alert kind="danger">{err}</Alert>}
                  <div className="form-grid">
                    <Field label="Decision"><Select value={status} onChange={setStatus} options={(PO_NEXT[d.po.status] ?? []).map((s) => ({ value: s, label: label(s) }))} placeholder="Select…" /></Field>
                    <Field label="Review notes" hint={status === 'verified' && cmp.discrepancy_count ? 'Required to verify a PO with discrepancies' : 'Recorded in the audit history'}>
                      <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />
                    </Field>
                  </div>
                  {status === 'verified' && cmp.discrepancy_count > 0 && (
                    <label className="checkbox"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I have reviewed the {cmp.discrepancy_count} discrepancies and accept this PO as the contract basis.</label>
                  )}
                  {status === 'verified' && <Alert kind="info">A verified PO becomes the approved contract value (X) used in receivables.</Alert>}
                  <div><button className="btn primary" disabled={!status || decide.isPending || (status === 'verified' && cmp.discrepancy_count > 0 && (!ack || !notes))} onClick={() => decide.mutate()}>{decide.isPending ? 'Saving…' : 'Record decision'}</button></div>
                </div>
              </div>
            )}
            {d.po.review_notes && <div className="card card-body"><div className="section-title">Review notes</div><p className="pre small">{d.po.review_notes}</p></div>}
            <div className="card">
              <div className="card-head"><h3><History size={16} style={{ verticalAlign: -3 }} /> Audit history</h3></div>
              <div className="feed">{d.history.map((h: any, i: number) => (
                <div key={i} className="feed-item"><div style={{ flex: 1 }}><b>{label(h.action)}</b> <span className="muted">by {h.user ?? 'system'}</span>
                  {h.changes?.status && <span> · {label(h.changes.status.from)} → {label(h.changes.status.to)}</span>}
                  {h.changes?.notes && <div className="small">{h.changes.notes}</div>}</div>
                  <span className="when">{dateTime(h.created_at)}</span></div>
              ))}</div>
            </div>
          </div>
        )}
      </QueryState>
    </Modal>
  )
}
