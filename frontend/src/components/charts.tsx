import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { label, money } from '../lib/format'

/* Validated categorical palette (fixed order, never cycled) and recessive chart chrome. */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
const AXIS = { stroke: '#9aa7b8', fontSize: 11 }
const GRID = '#eef1f5'
const tooltipStyle = { borderRadius: 8, border: '1px solid #e1e6ed', boxShadow: '0 6px 18px rgba(16,32,56,.12)', fontSize: 12 }

export function ProgressChart({ data }: { data: { code: string; name: string; progress: number; planned: number | null }[] }) {
  const rows = data.map((d) => ({ ...d, planned: d.planned ?? undefined }))
  return (
    <div className="chart-box" style={{ height: Math.max(220, rows.length * 34 + 60) }}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }} barGap={2} barCategoryGap="28%">
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" domain={[0, 100]} unit="%" tick={AXIS} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="code" width={118} tick={{ ...AXIS, fill: '#4d5b6e' }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(31,95,168,.06)' }}
            formatter={(v: number, n: string) => [`${v}%`, n === 'progress' ? 'Actual' : 'Planned (linear estimate)']}
            labelFormatter={(code) => rows.find((r) => r.code === code)?.name ?? code} />
          <Legend formatter={(v) => <span style={{ color: '#4d5b6e', fontSize: 12 }}>{v === 'progress' ? 'Actual progress' : 'Planned (linear estimate)'}</span>} />
          <Bar dataKey="progress" fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={10} />
          <Bar dataKey="planned" fill="#cbd3de" radius={[0, 4, 4, 0]} barSize={10} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function MonthlyPaymentsChart({ data, currencies }: { data: Record<string, number | string>[]; currencies: string[] }) {
  return (
    <div className="chart-box">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 0 }} barGap={2}>
          <CartesianGrid vertical={false} stroke={GRID} />
          <XAxis dataKey="month" tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(m: string) => {
            const [y, mo] = m.split('-')
            return new Date(+y, +mo - 1, 1).toLocaleDateString('en-GB', { month: 'short' })
          }} />
          <YAxis tick={AXIS} axisLine={false} tickLine={false} width={64} tickFormatter={(v) => money(v, currencies[0] ?? 'INR', { compact: true })} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(31,95,168,.06)' }} formatter={(v: number, n: string) => [money(v, n), `Verified receipts (${n})`]} />
          {currencies.length > 1 && <Legend />}
          {currencies.map((c, i) => <Bar key={c} dataKey={c} fill={SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={28} />)}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function OutstandingChart({ data }: { data: { code: string; currency: string; received: number; outstanding: number }[] }) {
  return (
    <div className="chart-box" style={{ height: Math.max(220, data.length * 34 + 60) }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }} barCategoryGap="30%">
          <CartesianGrid horizontal={false} stroke={GRID} />
          <XAxis type="number" tick={AXIS} axisLine={false} tickLine={false} tickFormatter={(v) => money(v, data[0]?.currency ?? 'INR', { compact: true })} />
          <YAxis type="category" dataKey="code" width={118} tick={{ ...AXIS, fill: '#4d5b6e' }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(31,95,168,.06)' }}
            formatter={(v: number, n: string, item: any) => [money(v, item.payload.currency), n === 'received' ? 'Verified received (Y)' : 'Outstanding (Z)']} />
          <Legend formatter={(v) => <span style={{ color: '#4d5b6e', fontSize: 12 }}>{v === 'received' ? 'Verified received (Y)' : 'Outstanding (Z)'}</span>} />
          <Bar dataKey="received" stackId="a" fill={SERIES[0]} stroke="#fff" strokeWidth={2} barSize={14} />
          <Bar dataKey="outstanding" stackId="a" fill={SERIES[1]} stroke="#fff" strokeWidth={2} radius={[0, 4, 4, 0]} barSize={14} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export function StatusChart({ data }: { data: { status: string; count: number }[] }) {
  const rows = data.map((d) => ({ ...d, name: label(d.status) }))
  return (
    <div className="chart-box" style={{ height: Math.max(180, rows.length * 38 + 30) }}>
      <ResponsiveContainer>
        <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 32, top: 4, bottom: 4 }}>
          <XAxis type="number" allowDecimals={false} hide />
          <YAxis type="category" dataKey="name" width={90} tick={{ ...AXIS, fill: '#4d5b6e' }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(31,95,168,.06)' }} formatter={(v: number) => [v, 'Projects']} />
          <Bar dataKey="count" fill={SERIES[0]} radius={[0, 4, 4, 0]} barSize={14} label={{ position: 'right', fill: '#344154', fontSize: 12 }} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
