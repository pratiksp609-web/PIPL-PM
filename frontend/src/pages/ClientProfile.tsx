import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Pencil } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { date, money } from '../lib/format'
import { Badge, Empty, Progress, QueryState, Stat, Tabs } from '../components/ui'
import { PageHead } from '../components/Layout'
import { ClientForm } from './Clients'

type Tab = 'projects' | 'quotations' | 'pos' | 'payments'

export default function ClientProfile() {
  const { id } = useParams()
  const session = useSession()
  const [tab, setTab] = useState<Tab>('projects')
  const [editing, setEditing] = useState(false)
  const q = useQuery({ queryKey: ['client', id], queryFn: () => api.get(`/api/clients/${id}`) })
  const d = q.data
  const projName = (pid: number) => d?.projects.find((p: any) => p.id === pid)?.code ?? `#${pid}`
  return (
    <QueryState q={q}>
      {d && (
        <>
          <Link to="/clients" className="small row" style={{ marginBottom: 8 }}><ArrowLeft size={14} /> Clients</Link>
          <PageHead title={d.client.company_name} sub={<>{d.client.name}{d.client.gstin && <> · GSTIN <span className="mono">{d.client.gstin}</span></>}</>}
            actions={session.permissions.manage_projects && <button className="btn" onClick={() => setEditing(true)}><Pencil size={14} /> Edit</button>} />
          <div className="grid grid-3 mb-16">
            <div className="card card-body">
              <div className="section-title">Contact</div>
              <dl className="dl">
                <dt>Contact person</dt><dd>{d.client.contact_person ?? '—'}</dd>
                <dt>Email</dt><dd>{d.client.email ? <a href={`mailto:${d.client.email}`}>{d.client.email}</a> : '—'}</dd>
                <dt>Phone</dt><dd>{d.client.phone ?? '—'}</dd>
                <dt>Billing address</dt><dd className="pre">{d.client.billing_address ?? '—'}</dd>
              </dl>
            </div>
            {d.receivables_total ? Object.entries(d.receivables_total as Record<string, any>).map(([cur, r]) => (
              <Stat key={cur} label={`Outstanding (${cur})`} value={money(r.outstanding, cur)}
                sub={<>X {money(r.contract_value, cur)} − Y {money(r.verified_received, cur)}{Number(r.credit) > 0 && <> · credit {money(r.credit, cur)}</>}</>} />
            )) : null}
            {d.receivables_total && Object.keys(d.receivables_total).length === 0 && <Stat label="Outstanding" value={money(0)} sub="No contract values yet" />}
            <Stat label="Projects" value={d.projects.length} sub={`${d.projects.filter((p: any) => p.status === 'active').length} active`} />
          </div>
          <div className="card">
            <div style={{ padding: '0 18px' }}>
              <Tabs value={tab} onChange={setTab} tabs={[
                { id: 'projects', label: `Projects (${d.projects.length})` },
                ...(d.quotations ? [
                  { id: 'quotations' as Tab, label: `Quotations (${d.quotations.length})` },
                  { id: 'pos' as Tab, label: `Purchase orders (${d.purchase_orders.length})` },
                  { id: 'payments' as Tab, label: `Payments & invoices (${d.payments.length})` },
                ] : []),
              ]} />
            </div>
            {tab === 'projects' && (d.projects.length === 0 ? <Empty title="No projects for this client" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Project</th><th>Status</th><th>Progress</th><th>Due</th>{d.receivables && <><th className="num">X</th><th className="num">Y</th><th className="num">Z</th></>}</tr></thead>
                <tbody>{d.projects.map((p: any) => {
                  const r = d.receivables?.[p.id]
                  return (
                    <tr key={p.id}>
                      <td><Link to={`/projects/${p.id}`} style={{ fontWeight: 600 }}>{p.name}</Link><div className="mono muted">{p.code}</div></td>
                      <td><Badge value={p.status} />{p.archived_at && <> <Badge text="Archived" /></>}</td>
                      <td style={{ minWidth: 140 }}><Progress value={p.progress} /></td>
                      <td>{date(p.expected_completion_date)}</td>
                      {r && <><td className="num">{money(r.contract_value, r.currency)}</td><td className="num">{money(r.verified_received, r.currency)}</td><td className="num"><b>{money(r.outstanding, r.currency)}</b></td></>}
                    </tr>
                  )
                })}</tbody>
              </table></div>
            ))}
            {tab === 'quotations' && (d.quotations.length === 0 ? <Empty title="No quotations" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Quotation</th><th>Project</th><th>Revision</th><th>Date</th><th>Status</th><th className="num">Total</th></tr></thead>
                <tbody>{d.quotations.map((x: any) => (
                  <tr key={x.version_id}><td className="mono">{x.quotation_number}</td><td><Link to={`/projects/${x.project_id}?tab=quotation`}>{projName(x.project_id)}</Link></td>
                    <td>R{x.revision_number}</td><td>{date(x.quotation_date)}</td><td><Badge value={x.status} /></td><td className="num">{money(x.total_amount, x.currency)}</td></tr>
                ))}</tbody>
              </table></div>
            ))}
            {tab === 'pos' && (d.purchase_orders.length === 0 ? <Empty title="No client purchase orders" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>PO number</th><th>Project</th><th>Issue date</th><th>Status</th><th className="num">Total value</th></tr></thead>
                <tbody>{d.purchase_orders.map((x: any) => (
                  <tr key={x.id}><td className="mono">{x.po_number}</td><td><Link to={`/projects/${x.project_id}?tab=client-po`}>{projName(x.project_id)}</Link></td>
                    <td>{date(x.issue_date)}</td><td><Badge value={x.status} /></td><td className="num">{money(x.total_value, x.currency)}</td></tr>
                ))}</tbody>
              </table></div>
            ))}
            {tab === 'payments' && (d.payments.length === 0 ? <Empty title="No payments recorded" /> : (
              <div className="table-wrap"><table className="table">
                <thead><tr><th>Date</th><th>Project</th><th>Invoice</th><th>Reference</th><th>Status</th><th className="num">Amount</th></tr></thead>
                <tbody>{d.payments.map((x: any) => (
                  <tr key={x.id}><td>{date(x.payment_date ?? x.due_date)}{!x.payment_date && <div className="small muted">due</div>}</td>
                    <td><Link to={`/projects/${x.project_id}?tab=payments`}>{projName(x.project_id)}</Link></td>
                    <td className="mono">{x.invoice_reference ?? '—'}</td><td className="mono">{x.transaction_reference ?? '—'}</td>
                    <td><Badge value={x.status} /></td><td className="num">{money(x.amount)}</td></tr>
                ))}</tbody>
              </table></div>
            ))}
          </div>
          {editing && <ClientForm client={d.client} onClose={() => setEditing(false)} />}
        </>
      )}
    </QueryState>
  )
}
