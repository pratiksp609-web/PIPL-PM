export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {}
    if (Array.isArray(this.details)) {
      for (const d of this.details as { field?: string; message?: string }[]) {
        if (d.field && d.message && !out[d.field]) out[d.field] = d.message
      }
    }
    return out
  }
}

function csrfToken(): string {
  const m = document.cookie.match(/(?:^|; )pipl_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

type Query = Record<string, string | number | boolean | null | undefined>

export function qs(params?: Query): string {
  if (!params) return ''
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '' || v === false) continue
    p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(method: string, url: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken()
  let payload: BodyInit | undefined
  if (body !== undefined) {
    if (isForm) payload = body as FormData
    else {
      headers['Content-Type'] = 'application/json'
      payload = JSON.stringify(body)
    }
  }
  let res: Response
  try {
    res = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection and try again.')
  }
  if (res.status === 401 && !url.endsWith('/auth/login') && !url.endsWith('/auth/me')) onUnauthorized?.()
  const ct = res.headers.get('content-type') || ''
  if (!res.ok) {
    if (ct.includes('application/json')) {
      const j = await res.json().catch(() => null)
      const e = j?.error
      throw new ApiError(res.status, e?.code || 'error', e?.message || `Request failed (${res.status})`, e?.details)
    }
    throw new ApiError(res.status, 'error', `Request failed (${res.status})`)
  }
  if (ct.includes('application/json')) return (await res.json()) as T
  return (await res.blob()) as unknown as T
}

export const api = {
  get: <T = any>(url: string, params?: Query) => request<T>('GET', url + qs(params)),
  post: <T = any>(url: string, body?: unknown, params?: Query) => request<T>('POST', url + qs(params), body ?? {}),
  patch: <T = any>(url: string, body: unknown) => request<T>('PATCH', url, body),
  put: <T = any>(url: string, body: unknown) => request<T>('PUT', url, body),
  del: <T = any>(url: string) => request<T>('DELETE', url),
  upload: <T = any>(url: string, form: FormData, params?: Query) => request<T>('POST', url + qs(params), form, true),
  blob: (url: string, params?: Query) => request<Blob>('GET', url + qs(params)),
}

/** Download a protected file through the authenticated API and save it with the given name. */
export async function downloadFile(url: string, filename: string, params?: Query) {
  const blob = await api.blob(url, params)
  const href = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = href
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 2000)
}
