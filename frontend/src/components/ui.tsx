import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Info, Inbox, X, XCircle } from 'lucide-react'
import { ApiError } from '../lib/api'
import { label, tone } from '../lib/format'

/* ------------------------------------------------------------- toasts */
type ToastKind = 'info' | 'success' | 'error'
interface ToastItem { id: number; kind: ToastKind; text: string }
const ToastCtx = createContext<(text: string, kind?: ToastKind) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const push = useCallback((text: string, kind: ToastKind = 'success') => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x, { id, kind, text }])
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 4000)
  }, [])
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.kind === 'error' ? <XCircle size={18} /> : t.kind === 'success' ? <CheckCircle2 size={18} /> : <Info size={18} />}
            <span style={{ flex: 1 }}>{t.text}</span>
            <button className="icon-btn" style={{ width: 22, height: 22, color: '#fff' }} onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export const useToast = () => useContext(ToastCtx)

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return 'Something went wrong'
}

/* ------------------------------------------------------------- basics */
export function Badge({ value, text, kind }: { value?: string | null; text?: ReactNode; kind?: string }) {
  if (!value && !text) return null
  return <span className={`badge ${kind ?? tone(value)}`}>{text ?? label(value)}</span>
}

export function Spinner({ block }: { block?: boolean }) {
  if (block) return <div className="loading-block"><span className="spinner" aria-label="Loading" /></div>
  return <span className="spinner" aria-label="Loading" />
}

export function Empty({ title, text, action, icon }: { title: string; text?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={36} />}
      <h3>{title}</h3>
      {text && <p>{text}</p>}
      {action && <div className="mt-16">{action}</div>}
    </div>
  )
}

export function Alert({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'danger' | 'ok'; children: ReactNode }) {
  const Icon = kind === 'danger' ? XCircle : kind === 'warn' ? AlertTriangle : kind === 'ok' ? CheckCircle2 : Info
  return <div className={`alert ${kind}`}><Icon size={16} /><div>{children}</div></div>
}

export function QueryState({ q, children, empty }: { q: { isLoading: boolean; error: unknown }; children: ReactNode; empty?: boolean }) {
  if (q.isLoading) return <Spinner block />
  if (q.error) return <div className="card-body"><Alert kind="danger">{errorMessage(q.error)}</Alert></div>
  if (empty) return null
  return <>{children}</>
}

export function Progress({ value, plan, overdue }: { value: number; plan?: number | null; overdue?: boolean }) {
  const cls = overdue ? 'danger' : value >= 100 ? 'ok' : plan != null && plan - value >= 15 ? 'warn' : ''
  return (
    <div className="progress-cell" title={plan != null ? `Actual ${value}% · Planned (linear estimate) ${plan}%` : `${value}%`}>
      <div className={`progress ${cls}`} style={{ flex: 1 }}>
        <span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
        {plan != null && <i className="plan" style={{ left: `${plan}%` }} />}
      </div>
      <span className="pct">{value}%</span>
    </div>
  )
}

export function Stat({ label: l, value, sub, tone: t, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode }) {
  return (
    <div className={`card stat ${t ?? ''}`}>
      <div className="label">{icon}{l}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

/* ------------------------------------------------------------- modal / confirm */
export function Modal({ title, onClose, children, footer, size }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: 'sm' | 'lg' | 'xl' }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prev = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      prev?.focus?.()
    }
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${size ?? ''}`} role="dialog" aria-modal="true" ref={ref}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

interface ConfirmOpts { title: string; message: ReactNode; confirmText?: string; danger?: boolean }
const ConfirmCtx = createContext<(o: ConfirmOpts) => Promise<boolean>>(async () => false)

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<(ConfirmOpts & { resolve: (v: boolean) => void }) | null>(null)
  const confirm = useCallback((o: ConfirmOpts) => new Promise<boolean>((resolve) => setState({ ...o, resolve })), [])
  const close = (v: boolean) => {
    state?.resolve(v)
    setState(null)
  }
  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {state && (
        <Modal title={state.title} onClose={() => close(false)} size="sm"
          footer={<>
            <button className="btn" onClick={() => close(false)}>Cancel</button>
            <button className={`btn ${state.danger ? 'danger' : 'primary'}`} onClick={() => close(true)}>{state.confirmText ?? 'Confirm'}</button>
          </>}>
          <div>{state.message}</div>
        </Modal>
      )}
    </ConfirmCtx.Provider>
  )
}

export const useConfirm = () => useContext(ConfirmCtx)

/* ------------------------------------------------------------- form fields */
export function Field({ label: l, required, hint, error, children, className }: { label: ReactNode; required?: boolean; hint?: ReactNode; error?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`field ${className ?? ''}`}>
      <label>{l}{required && <span className="req"> *</span>}</label>
      {children}
      {error ? <span className="err">{error}</span> : hint ? <span className="hint">{hint}</span> : null}
    </div>
  )
}

export function Select({ value, onChange, options, placeholder, className, ...rest }: {
  value: string | number | null | undefined
  onChange: (v: string) => void
  options: { value: string | number; label: string }[]
  placeholder?: string
  className?: string
  disabled?: boolean
  'aria-label'?: string
}) {
  return (
    <select className={`input ${className ?? ''}`} value={value ?? ''} onChange={(e) => onChange(e.target.value)} {...rest}>
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

export const opts = (values: readonly string[]) => values.map((v) => ({ value: v, label: label(v) }))

/* ------------------------------------------------------------- tables */
export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total === 0) return null
  const from = (page - 1) * pageSize + 1
  const to = Math.min(total, page * pageSize)
  return (
    <div className="pagination">
      <span>Showing {from}–{to} of {total}</span>
      <div className="row">
        <button className="btn sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft size={14} /> Prev</button>
        <span>Page {page} of {pages}</span>
        <button className="btn sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">Next <ChevronRight size={14} /></button>
      </div>
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={`tab ${value === t.id ? 'active' : ''}`} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Seg<T extends string>({ options, value, onChange }: { options: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="seg" role="radiogroup">
      {options.map((o) => (
        <button key={o.id} role="radio" aria-checked={value === o.id} className={value === o.id ? 'active' : ''} onClick={() => onChange(o.id)}>{o.label}</button>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------- hooks */
export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

/** Form state helper: values, setter, server field errors and a guarded submit that prevents double submission. */
export function useForm<T extends Record<string, any>>(initial: T) {
  const [values, setValues] = useState<T>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const set = <K extends keyof T>(k: K, v: T[K]) => setValues((s) => ({ ...s, [k]: v }))
  const submit = async (fn: () => Promise<void>) => {
    if (submitting) return
    setSubmitting(true)
    setErrors({})
    setFormError(null)
    try {
      await fn()
    } catch (e) {
      if (e instanceof ApiError) {
        setErrors(e.fieldErrors())
        setFormError(e.message)
      } else setFormError(errorMessage(e))
      throw e
    } finally {
      setSubmitting(false)
    }
  }
  return { values, set, setValues, errors, setErrors, submitting, formError, setFormError, submit }
}

/** Remove empty strings so optional fields are sent as null-equivalents. */
export function clean<T extends Record<string, any>>(obj: T): Partial<T> {
  const out: Record<string, any> = {}
  for (const [k, v] of Object.entries(obj)) out[k] = v === '' ? null : v
  return out as Partial<T>
}
