export function money(v: string | number | null | undefined, currency = 'INR', opts: { compact?: boolean } = {}): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = typeof v === 'number' ? v : Number(v)
  if (Number.isNaN(n)) return '—'
  try {
    return new Intl.NumberFormat(currency === 'INR' ? 'en-IN' : 'en-US', {
      style: 'currency',
      currency,
      maximumFractionDigits: opts.compact ? 1 : 2,
      notation: opts.compact ? 'compact' : 'standard',
    }).format(n)
  } catch {
    return `${currency} ${n.toFixed(2)}`
  }
}

export function num(v: string | number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  return Number.isNaN(n) ? '—' : n.toLocaleString('en-IN', { maximumFractionDigits: digits })
}

/** Parse YYYY-MM-DD as a local date (avoids UTC shifting of date-only values). */
export function parseDate(d: string): Date {
  if (/^\d{4}-\d{2}-\d{2}$/.test(d)) {
    const [y, m, day] = d.split('-').map(Number)
    return new Date(y, m - 1, day)
  }
  return new Date(d)
}

export function date(d: string | null | undefined): string {
  if (!d) return '—'
  return parseDate(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export function dateTime(d: string | null | undefined): string {
  if (!d) return '—'
  return new Date(d).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function relative(d: string | null | undefined): string {
  if (!d) return '—'
  const diff = (Date.now() - new Date(d).getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`
  return date(d)
}

export function isoDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function todayIso(): string {
  return isoDate(new Date())
}

export function daysUntil(d: string | null | undefined): number | null {
  if (!d) return null
  const t = new Date()
  t.setHours(0, 0, 0, 0)
  return Math.round((parseDate(d).getTime() - t.getTime()) / 86400000)
}

export function label(s: string | null | undefined): string {
  if (!s) return '—'
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function initials(name: string): string {
  return name
    .replace(/\[.*?\]/g, '')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

type Tone = 'ok' | 'warn' | 'danger' | 'info' | 'violet' | 'accent' | ''

const TONES: Record<string, Tone> = {
  // project
  planning: 'info', active: 'ok', on_hold: 'warn', completed: 'violet', cancelled: '',
  // priority
  low: '', medium: 'info', high: 'warn', critical: 'danger',
  // quotation
  draft: '', submitted: 'info', approved: 'ok', rejected: 'danger', expired: 'warn', superseded: '',
  // client po
  received: 'info', under_review: 'warn', verified: 'ok',
  // payment
  recorded: 'info', pending: 'warn', failed: 'danger', reversed: 'danger',
  // procurement
  rfq: 'info', ordered: 'info', partially_received: 'warn', delayed: 'danger',
  // tasks
  todo: '', in_progress: 'info', blocked: 'danger', // under_review shared
  // health
  on_track: 'ok', at_risk: 'warn',
  // ai
  success: 'ok', not_configured: '', skipped: '',
}

export function tone(s: string | null | undefined): Tone {
  return (s && TONES[s]) || ''
}

export const ROLE_LABEL: Record<string, string> = { admin: 'Admin', project_manager: 'Project Manager', team_member: 'Team Member' }
export const CURRENCIES = ['INR', 'USD', 'EUR', 'GBP', 'AED']
