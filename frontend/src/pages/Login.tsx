import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { CheckCircle2, Eye, EyeOff, LogIn } from 'lucide-react'
import { useAuth } from '../lib/auth'
import { Alert, Field, errorMessage } from '../components/ui'

export default function Login() {
  const { session, login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation() as { state?: { from?: string } }
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [touched, setTouched] = useState(false)

  if (session) return <Navigate to={loc.state?.from || '/'} replace />

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (!identifier.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      await login(identifier.trim(), password)
      nav(loc.state?.from || '/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-page">
      <section className="login-hero">
        <div className="grid-lines" />
        <div style={{ position: 'relative' }}>
          <div className="row" style={{ gap: 12 }}>
            <div className="brand-mark" style={{ width: 44, height: 44 }}>
              <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden><path d="M9 25V7h8.5a5.5 5.5 0 0 1 0 11H13" stroke="#f0a43a" strokeWidth="3.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <div><strong style={{ color: '#fff', fontSize: 18 }}>PIPL</strong><div className="small" style={{ color: '#8ea2bd' }}>AI Project Management System</div></div>
          </div>
          <h1>Engineering, procurement and turnkey projects — one source of truth.</h1>
          <p style={{ maxWidth: 460 }}>Track every project from quotation to final payment, with procurement, progress and reporting connected through the project ID.</p>
          <ul>
            <li><CheckCircle2 size={18} /> Quotations, client POs and version history</li>
            <li><CheckCircle2 size={18} /> Receivables calculated as X − Y = Z from verified records</li>
            <li><CheckCircle2 size={18} /> BOM procurement and supplier deliveries</li>
            <li><CheckCircle2 size={18} /> Daily updates, reminders and AI-assisted status reports</li>
          </ul>
        </div>
        <div className="small" style={{ position: 'relative', color: '#6f84a2' }}>Authorized personnel only. Activity is recorded in the audit log.</div>
      </section>
      <section className="login-panel">
        <form className="login-card card card-body" onSubmit={submit} noValidate>
          <h2>Sign in</h2>
          <p className="muted mb-16">Use your company email or username.</p>
          <div className="form">
            {error && <Alert kind="danger">{error}</Alert>}
            <Field label="Email or username" required error={touched && !identifier.trim() ? 'Enter your email or username' : undefined}>
              <input className="input" autoComplete="username" autoFocus value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
            </Field>
            <Field label="Password" required error={touched && !password ? 'Enter your password' : undefined}>
              <div style={{ position: 'relative' }}>
                <input className="input" type={show ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ paddingRight: 40 }} />
                <button type="button" className="icon-btn" style={{ position: 'absolute', right: 2, top: 0, height: 37 }} onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'}>
                  {show ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </Field>
            <button className="btn primary" type="submit" disabled={busy} style={{ width: '100%', padding: '10px 14px' }}>
              {busy ? <span className="spinner" style={{ width: 16, height: 16, borderTopColor: '#fff' }} /> : <LogIn size={16} />} Sign in
            </button>
            <p className="small muted">Forgot your password? Ask an administrator to reset it from Settings → Users.</p>
          </div>
        </form>
      </section>
    </div>
  )
}
