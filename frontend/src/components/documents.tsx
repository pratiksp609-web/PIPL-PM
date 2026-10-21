import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Eye, FileText, RefreshCw, Trash2, UploadCloud, X } from 'lucide-react'
import { api, downloadFile } from '../lib/api'
import { useSession } from '../lib/auth'
import { useProjectOptions } from '../lib/hooks'
import { dateTime, fileSize, label } from '../lib/format'
import { Alert, Badge, Empty, Field, Modal, Pagination, QueryState, Select, Spinner, errorMessage, useConfirm, useDebounced, useToast } from './ui'

export const DOC_CATEGORIES = ['quotation', 'client_po', 'supplier_po', 'invoice', 'payment_proof', 'report', 'drawing', 'other'] as const
const FIN = ['quotation', 'client_po', 'supplier_po', 'invoice', 'payment_proof']
export const ACCEPT = '.pdf,.docx,.doc,.xlsx,.xls,.csv,.txt,.png,.jpg,.jpeg'
const MAX_MB = 25

export function FilePicker({ file, onFile, accept = ACCEPT }: { file: File | null; onFile: (f: File | null) => void; accept?: string }) {
  const ref = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const pick = (f: File | undefined) => {
    setErr(null)
    if (!f) return
    const ext = f.name.split('.').pop()?.toLowerCase() ?? ''
    if (!accept.split(',').includes(`.${ext}`)) return setErr(`.${ext} files are not allowed`)
    if (f.size > MAX_MB * 1024 * 1024) return setErr(`File is larger than ${MAX_MB} MB`)
    if (f.size === 0) return setErr('File is empty')
    onFile(f)
  }
  if (file)
    return (
      <div className="file-pill">
        <FileText size={20} className="muted" />
        <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis' }}>{file.name}</div><div className="small muted">{fileSize(file.size)}</div></div>
        <button className="icon-btn" onClick={() => onFile(null)} aria-label="Remove file"><X size={16} /></button>
      </div>
    )
  return (
    <>
      <div className={`dropzone ${drag ? 'drag' : ''}`} role="button" tabIndex={0} onClick={() => ref.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && ref.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}>
        <UploadCloud size={28} />
        <div style={{ fontWeight: 600, color: 'var(--steel-700)' }}>Drop a file here or click to browse</div>
        <div className="small">PDF, DOCX, XLSX, CSV, TXT, PNG, JPG · up to {MAX_MB} MB</div>
      </div>
      <input ref={ref} type="file" accept={accept} hidden onChange={(e) => { pick(e.target.files?.[0]); e.target.value = '' }} />
      {err && <div className="err small" style={{ color: 'var(--danger)' }}>{err}</div>}
    </>
  )
}

/** Authenticated preview: PDFs and images are fetched as blobs; DOCX/XLSX/TXT render server-sanitised content. */
export function DocumentPreview({ doc, onClose }: { doc: any; onClose: () => void }) {
  const [state, setState] = useState<{ loading: boolean; error?: string; url?: string; html?: string; text?: string; rows?: string[][] }>({ loading: true })
  useEffect(() => {
    let url: string | undefined
    let cancelled = false
    ;(async () => {
      try {
        if (['pdf', 'png', 'jpg', 'jpeg'].includes(doc.extension)) {
          const blob = await api.blob(`/api/documents/${doc.id}/preview`)
          url = URL.createObjectURL(blob)
          if (!cancelled) setState({ loading: false, url })
        } else {
          const r = await api.get(`/api/documents/${doc.id}/preview`)
          if (!cancelled) setState({ loading: false, html: r.html, text: r.text, rows: r.rows })
        }
      } catch (e) {
        if (!cancelled) setState({ loading: false, error: errorMessage(e) })
      }
    })()
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [doc.id, doc.extension])
  return (
    <Modal title={doc.title} onClose={onClose} size="xl"
      footer={<><span className="muted small" style={{ marginRight: 'auto' }}>{doc.original_filename} · {fileSize(doc.size_bytes ?? 0)}</span>
        <button className="btn" onClick={() => downloadFile(`/api/documents/${doc.id}/download`, doc.original_filename)}><Download size={14} /> Download</button>
        <button className="btn primary" onClick={onClose}>Close</button></>}>
      {state.loading && <Spinner block />}
      {state.error && <Alert kind="warn">{state.error}</Alert>}
      {state.url && doc.extension === 'pdf' && <iframe className="preview-frame" src={state.url} title={doc.title} />}
      {state.url && doc.extension !== 'pdf' && <img className="preview-img" src={state.url} alt={doc.title} />}
      {state.html !== undefined && <div className="preview-html" dangerouslySetInnerHTML={{ __html: state.html }} />}
      {state.text !== undefined && <pre className="preview-html mono" style={{ whiteSpace: 'pre-wrap' }}>{state.text}</pre>}
      {state.rows && (
        <div className="table-wrap preview-html" style={{ padding: 0 }}>
          <table className="table"><tbody>{state.rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
        </div>
      )}
    </Modal>
  )
}

export function UploadModal({ projectId, category: fixedCategory, links, onClose, onUploaded, title }: {
  projectId?: number; category?: string; links?: Record<string, number | undefined>; onClose: () => void; onUploaded?: (r: any) => void; title?: string
}) {
  const session = useSession()
  const projects = useProjectOptions()
  const qc = useQueryClient()
  const toast = useToast()
  const [file, setFile] = useState<File | null>(null)
  const [pid, setPid] = useState<string>(projectId ? String(projectId) : '')
  const [category, setCategory] = useState(fixedCategory ?? 'other')
  const [docTitle, setDocTitle] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cats = DOC_CATEGORIES.filter((c) => session.permissions.finance || !FIN.includes(c))
  const upload = async () => {
    if (!file || !pid || busy) return
    setBusy(true)
    setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('project_id', pid)
      form.append('category', category)
      if (docTitle) form.append('title', docTitle)
      if (description) form.append('description', description)
      for (const [k, v] of Object.entries(links ?? {})) if (v) form.append(k, String(v))
      const r = await api.upload('/api/documents', form)
      toast('File uploaded')
      qc.invalidateQueries({ queryKey: ['documents'] })
      onUploaded?.(r)
      onClose()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal title={title ?? 'Upload document'} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!file || !pid || busy} onClick={upload}>{busy ? 'Uploading…' : 'Upload'}</button></>}>
      <div className="form">
        {error && <Alert kind="danger">{error}</Alert>}
        <FilePicker file={file} onFile={setFile} />
        {!projectId && <Field label="Project" required><Select value={pid} onChange={setPid} options={projects.data ?? []} placeholder="Select project" /></Field>}
        {!fixedCategory && <Field label="Category" required><Select value={category} onChange={setCategory} options={cats.map((c) => ({ value: c, label: label(c) }))} /></Field>}
        <Field label="Title" hint="Defaults to the file name"><input className="input" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} maxLength={255} /></Field>
        <Field label="Description"><textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}

export function DocumentsPanel({ projectId, fixedFilters }: { projectId?: number; fixedFilters?: Record<string, string | number> }) {
  const session = useSession()
  const projects = useProjectOptions(true)
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const [q, setQ] = useState('')
  const dq = useDebounced(q)
  const [category, setCategory] = useState('')
  const [pid, setPid] = useState('')
  const [range, setRange] = useState({ date_from: '', date_to: '' })
  const [current, setCurrent] = useState(false)
  const [page, setPage] = useState(1)
  const [preview, setPreview] = useState<any | null>(null)
  const [upload, setUpload] = useState(false)
  const replaceRef = useRef<HTMLInputElement>(null)
  const [replacing, setReplacing] = useState<any | null>(null)
  const params = { q: dq, category, project_id: projectId ?? pid, page, page_size: 20, include_superseded: !current, ...range, ...fixedFilters }
  const list = useQuery({ queryKey: ['documents', params], queryFn: () => api.get('/api/documents', params) })
  const del = useMutation({
    mutationFn: (id: number) => api.del(`/api/documents/${id}`),
    onSuccess: () => { toast('Document deleted'); qc.invalidateQueries({ queryKey: ['documents'] }) },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const doReplace = async (f: File | undefined) => {
    if (!f || !replacing) return
    const form = new FormData()
    form.append('file', f)
    try {
      await api.upload(`/api/documents/${replacing.id}/replace`, form)
      toast('New version uploaded; the previous file is kept in history')
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['quotations'] })
      qc.invalidateQueries({ queryKey: ['client-pos'] })
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setReplacing(null)
    }
  }
  const cats = DOC_CATEGORIES.filter((c) => session.permissions.finance || !FIN.includes(c))
  return (
    <div className="card">
      <div className="card-head">
        <div><h3>Documents</h3><p>Files are stored privately and only served to authorised users.</p></div>
        <button className="btn primary sm" onClick={() => setUpload(true)}><UploadCloud size={14} /> Upload</button>
      </div>
      <div className="filters" style={{ borderRadius: 0 }}>
        <Field label="Search" className="grow"><input className="input" placeholder="Title, file name or text inside documents" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} /></Field>
        {!projectId && <Field label="Project"><Select value={pid} onChange={(v) => { setPid(v); setPage(1) }} options={projects.data ?? []} placeholder="All projects" /></Field>}
        <Field label="Category"><Select value={category} onChange={(v) => { setCategory(v); setPage(1) }} options={cats.map((c) => ({ value: c, label: label(c) }))} placeholder="All" /></Field>
        <Field label="Uploaded from"><input type="date" className="input" value={range.date_from} onChange={(e) => setRange((r) => ({ ...r, date_from: e.target.value }))} /></Field>
        <Field label="to"><input type="date" className="input" value={range.date_to} onChange={(e) => setRange((r) => ({ ...r, date_to: e.target.value }))} /></Field>
        <label className="checkbox"><input type="checkbox" checked={current} onChange={(e) => setCurrent(e.target.checked)} /> Current versions only</label>
      </div>
      <QueryState q={list}>
        {list.data?.items.length === 0 ? <Empty icon={<FileText size={36} />} title="No documents" text="Upload quotations, POs, invoices, drawings and other project files." /> : (
          <div className="table-wrap"><table className="table">
            <thead><tr><th>Document</th>{!projectId && <th>Project</th>}<th>Category</th><th>Size</th><th>Uploaded</th><th /></tr></thead>
            <tbody>{list.data?.items.map((d: any) => (
              <tr key={d.id} className={d.superseded_by_id ? 'muted-row' : ''}>
                <td>
                  <button className="btn ghost xs" style={{ padding: 0, fontWeight: 600, color: 'var(--primary)' }} onClick={() => setPreview(d)}>{d.title}</button>
                  <div className="small muted">{d.original_filename}</div>
                  {d.superseded_by_id && <Badge text="Superseded" />}
                </td>
                {!projectId && <td className="small">{d.project}</td>}
                <td><Badge text={label(d.category)} kind="outline" /></td>
                <td className="nowrap">{fileSize(d.size_bytes)} · {d.extension.toUpperCase()}</td>
                <td className="small nowrap">{dateTime(d.created_at)}<div className="muted">{d.uploaded_by}</div></td>
                <td className="actions">
                  <button className="btn xs ghost" title="Preview" aria-label="Preview" onClick={() => setPreview(d)}><Eye size={14} /></button>
                  <button className="btn xs ghost" title="Download" aria-label="Download" onClick={() => downloadFile(`/api/documents/${d.id}/download`, d.original_filename).catch((e) => toast(errorMessage(e), 'error'))}><Download size={14} /></button>
                  {!d.superseded_by_id && <button className="btn xs ghost" title="Replace with new version" aria-label="Replace" onClick={() => { setReplacing(d); replaceRef.current?.click() }}><RefreshCw size={14} /></button>}
                  {session.permissions.manage_projects && <button className="btn xs ghost" title="Delete" aria-label="Delete" onClick={async () => {
                    if (await confirm({ title: 'Delete document?', message: `“${d.title}” will be removed from lists. The audit log keeps a record of the deletion.`, danger: true, confirmText: 'Delete' })) del.mutate(d.id)
                  }}><Trash2 size={14} /></button>}
                </td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {list.data && <Pagination page={page} pageSize={20} total={list.data.total} onPage={setPage} />}
      </QueryState>
      <input ref={replaceRef} type="file" accept={ACCEPT} hidden onChange={(e) => { doReplace(e.target.files?.[0]); e.target.value = '' }} />
      {preview && <DocumentPreview doc={preview} onClose={() => setPreview(null)} />}
      {upload && <UploadModal projectId={projectId} onClose={() => setUpload(false)} />}
    </div>
  )
}

export function DocLink({ doc }: { doc: { id: number; title: string; extension: string; original_filename: string } | null }) {
  const [open, setOpen] = useState(false)
  if (!doc) return <span className="muted small">No document</span>
  return (
    <>
      <button className="btn xs" onClick={() => setOpen(true)}><Eye size={13} /> {doc.extension.toUpperCase()}</button>
      {open && <DocumentPreview doc={doc} onClose={() => setOpen(false)} />}
    </>
  )
}
