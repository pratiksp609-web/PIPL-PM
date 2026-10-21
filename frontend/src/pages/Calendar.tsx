import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Plus, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import { useSession } from '../lib/auth'
import { useProjectOptions } from '../lib/hooks'
import { isoDate, label, parseDate } from '../lib/format'
import { Alert, Field, Modal, QueryState, Seg, Select, errorMessage, useConfirm, useDebounced, useForm, useToast } from '../components/ui'
import { PageHead } from '../components/Layout'

type View = 'day' | 'week' | 'month' | 'year'
const CATEGORIES = ['project_deadline', 'task_due', 'meeting', 'quotation_expiry', 'payment_due', 'supplier_delivery', 'reminder', 'milestone', 'other']
const FINANCE = ['quotation_expiry', 'payment_due', 'supplier_delivery']
const EVENT_TYPES = ['meeting', 'reminder', 'milestone', 'other']
const DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const HOUR_PX = 44
const YEARS_RANGE = 50

const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
const startOfWeek = (d: Date) => addDays(d, -((d.getDay() + 6) % 7))
const sameDay = (a: Date, b: Date) => isoDate(a) === isoDate(b)

function limits() {
  const t = new Date()
  return { min: new Date(t.getFullYear() - YEARS_RANGE, t.getMonth(), 1), max: new Date(t.getFullYear() + YEARS_RANGE, t.getMonth(), 28) }
}

function rangeFor(view: View, c: Date): [Date, Date] {
  if (view === 'day') return [c, c]
  if (view === 'week') { const s = startOfWeek(c); return [s, addDays(s, 6)] }
  if (view === 'month') { const s = startOfWeek(new Date(c.getFullYear(), c.getMonth(), 1)); return [s, addDays(s, 41)] }
  return [new Date(c.getFullYear(), 0, 1), new Date(c.getFullYear(), 11, 31)]
}

function shift(view: View, c: Date, dir: number): Date {
  if (view === 'day') return addDays(c, dir)
  if (view === 'week') return addDays(c, 7 * dir)
  if (view === 'month') return new Date(c.getFullYear(), c.getMonth() + dir, 1)
  return new Date(c.getFullYear() + dir, c.getMonth(), 1)
}

interface Item { id: string; category: string; title: string; start: string; end: string | null; all_day: boolean; editable: boolean; link: string | null; source_id?: number; overdue?: boolean; description?: string; location?: string; [k: string]: any }

const startOf = (i: Item) => parseDate(i.start)
const isTimed = (i: Item) => !i.all_day && i.start.length > 10

/** Day keys (YYYY-MM-DD) an item covers, capped to keep long events cheap to render. */
function daysOf(i: Item): string[] {
  const s = startOf(i)
  const e = i.end ? parseDate(i.end) : s
  const out: string[] = []
  for (let d = new Date(s.getFullYear(), s.getMonth(), s.getDate()); d <= e && out.length < 62; d = addDays(d, 1)) out.push(isoDate(d))
  return out.length ? out : [isoDate(s)]
}

export default function CalendarPage() {
  const session = useSession()
  const nav = useNavigate()
  const [view, setView] = useState<View>('month')
  const [cursor, setCursor] = useState(() => new Date())
  const [search, setSearch] = useState('')
  const dsearch = useDebounced(search)
  const allowed = CATEGORIES.filter((c) => session.permissions.finance || !FINANCE.includes(c))
  const [enabled, setEnabled] = useState<string[]>(allowed)
  const [projectId, setProjectId] = useState('')
  const projects = useProjectOptions()
  const [editing, setEditing] = useState<{ item?: Item; start?: Date; allDay?: boolean } | null>(null)
  const lim = limits()
  const [from, to] = rangeFor(view, cursor)
  const q = useQuery({
    queryKey: ['calendar', isoDate(from), isoDate(to), enabled.join(','), projectId, dsearch],
    queryFn: () => api.get('/api/calendar', { start: isoDate(from), end: isoDate(to), categories: enabled.join(','), project_id: projectId, q: dsearch }),
    enabled: enabled.length > 0,
    placeholderData: (prev) => prev,
  })
  const items: Item[] = useMemo(() => (enabled.length ? q.data?.items ?? [] : []), [enabled.length, q.data])
  const byDay = useMemo(() => {
    const m = new Map<string, Item[]>()
    for (const i of items) for (const k of daysOf(i)) m.set(k, [...(m.get(k) ?? []), i])
    return m
  }, [items])

  const go = (d: Date) => { if (d >= lim.min && d <= lim.max) setCursor(d) }
  const canPrev = rangeFor(view, shift(view, cursor, -1))[1] >= lim.min
  const canNext = rangeFor(view, shift(view, cursor, 1))[0] <= lim.max
  const open = (i: Item) => {
    if (i.editable && i.entity_type === 'event') setEditing({ item: i })
    else if (i.link) nav(i.link)
  }
  const title = view === 'year' ? String(cursor.getFullYear())
    : view === 'month' ? `${MONTHS[cursor.getMonth()]} ${cursor.getFullYear()}`
    : view === 'week' ? `${from.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} – ${to.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}`
    : cursor.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

  return (
    <>
      <PageHead title="Calendar" sub="Deadlines, tasks, meetings, quotation expiries, payments and supplier deliveries in one place."
        actions={<button className="btn primary" onClick={() => setEditing({ start: new Date(cursor.getFullYear(), cursor.getMonth(), cursor.getDate(), 10), allDay: false })}><Plus size={16} /> New event</button>} />
      <div className="card">
        <div className="cal-toolbar">
          <button className="btn sm" onClick={() => setCursor(new Date())}>Today</button>
          <button className="icon-btn" aria-label="Previous" disabled={!canPrev} onClick={() => setCursor(shift(view, cursor, -1))}><ChevronLeft size={18} /></button>
          <button className="icon-btn" aria-label="Next" disabled={!canNext} onClick={() => setCursor(shift(view, cursor, 1))}><ChevronRight size={18} /></button>
          <div className="cal-title">{title}</div>
          <input type="date" className="input sm" style={{ width: 150 }} aria-label="Go to date" min={isoDate(lim.min)} max={isoDate(lim.max)} value={isoDate(cursor)}
            onChange={(e) => e.target.value && go(parseDate(e.target.value))} />
          <div style={{ flex: 1 }} />
          <input className="input sm" style={{ width: 180 }} placeholder="Search calendar…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search calendar" />
          <Select className="sm" value={projectId} onChange={setProjectId} options={projects.data ?? []} placeholder="All projects" aria-label="Project filter" />
          <Seg value={view} onChange={setView} options={[{ id: 'day', label: 'Day' }, { id: 'week', label: 'Week' }, { id: 'month', label: 'Month' }, { id: 'year', label: 'Year' }]} />
        </div>
        <div className="cal-toolbar" style={{ paddingTop: 8, paddingBottom: 8 }}>
          <div className="legend">
            {allowed.map((c) => (
              <button key={c} className={enabled.includes(c) ? '' : 'off'} aria-pressed={enabled.includes(c)}
                onClick={() => setEnabled((s) => (s.includes(c) ? s.filter((x) => x !== c) : [...s, c]))}>
                <span className={`sw cat-${c}`} />{label(c)}
              </button>
            ))}
          </div>
          <button className="btn xs ghost" onClick={() => setEnabled(enabled.length === allowed.length ? [] : allowed)}>{enabled.length === allowed.length ? 'Hide all' : 'Show all'}</button>
          {q.isFetching && <span className="small muted">Loading…</span>}
        </div>
        {enabled.length === 0 && <div className="card-body"><Alert kind="info">All categories are hidden. Turn on at least one category above.</Alert></div>}
        <QueryState q={{ isLoading: q.isLoading && enabled.length > 0, error: q.error }}>
          {view === 'month' && <MonthView from={from} cursor={cursor} byDay={byDay} onOpen={open} onDay={(d) => { setCursor(d); setView('day') }}
            onCreate={(d) => setEditing({ start: d, allDay: true })} />}
          {(view === 'week' || view === 'day') && <TimeGrid days={view === 'week' ? Array.from({ length: 7 }, (_, i) => addDays(from, i)) : [cursor]} items={items} byDay={byDay}
            onOpen={open} onCreate={(d, allDay) => setEditing({ start: d, allDay })} onDay={(d) => { setCursor(d); setView('day') }} />}
          {view === 'year' && <YearView year={cursor.getFullYear()} byDay={byDay} onDay={(d) => { setCursor(d); setView('day') }} onMonth={(m) => { setCursor(new Date(cursor.getFullYear(), m, 1)); setView('month') }} />}
        </QueryState>
      </div>
      {editing && <EventForm item={editing.item} start={editing.start} allDay={editing.allDay} onClose={() => setEditing(null)} />}
    </>
  )
}

function Ev({ i, onOpen }: { i: Item; onOpen: (i: Item) => void }) {
  const time = isTimed(i) ? startOf(i).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + ' ' : ''
  return (
    <button className={`cal-ev cat-${i.category}`} title={`${label(i.category)}: ${i.title}${i.overdue ? ' (overdue)' : ''}${i.location ? ` · ${i.location}` : ''}`}
      onClick={(e) => { e.stopPropagation(); onOpen(i) }} style={i.overdue ? { outline: '1px dashed var(--danger)' } : undefined}>
      {time}{i.title}
    </button>
  )
}

function MonthView({ from, cursor, byDay, onOpen, onDay, onCreate }: { from: Date; cursor: Date; byDay: Map<string, Item[]>; onOpen: (i: Item) => void; onDay: (d: Date) => void; onCreate: (d: Date) => void }) {
  const today = new Date()
  return (
    <div className="cal-month">
      {DOW.map((d) => <div key={d} className="cal-dow">{d}</div>)}
      {Array.from({ length: 42 }, (_, n) => {
        const d = addDays(from, n)
        const list = byDay.get(isoDate(d)) ?? []
        return (
          <div key={n} className={`cal-cell ${d.getMonth() !== cursor.getMonth() ? 'other' : ''} ${sameDay(d, today) ? 'today' : ''}`} onClick={() => onCreate(d)}
            role="gridcell" aria-label={`${d.toDateString()}, ${list.length} items. Click to add an event`}>
            <button className="cal-daynum link-btn" onClick={(e) => { e.stopPropagation(); onDay(d) }}>{d.getDate()}</button>
            {list.slice(0, 3).map((i) => <Ev key={i.id} i={i} onOpen={onOpen} />)}
            {list.length > 3 && <button className="cal-more link-btn" onClick={(e) => { e.stopPropagation(); onDay(d) }}>+{list.length - 3} more</button>}
          </div>
        )
      })}
    </div>
  )
}

function TimeGrid({ days, items, byDay, onOpen, onCreate, onDay }: { days: Date[]; items: Item[]; byDay: Map<string, Item[]>; onOpen: (i: Item) => void; onCreate: (d: Date, allDay: boolean) => void; onDay: (d: Date) => void }) {
  const scroller = useRef<HTMLDivElement>(null)
  useEffect(() => { scroller.current?.scrollTo({ top: 7 * HOUR_PX }) }, [])
  const today = new Date()
  const timed = items.filter(isTimed)
  return (
    <div>
      <div className={`cal-week ${days.length === 1 ? 'day' : ''}`}>
        <div />
        {days.map((d) => <button key={isoDate(d)} className={`cal-colhead link-btn ${sameDay(d, today) ? 'today' : ''}`} style={{ color: sameDay(d, today) ? undefined : 'inherit' }} onClick={() => onDay(d)}>
          {d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}</button>)}
        <div className="small muted" style={{ padding: 4, textAlign: 'right' }}>All day</div>
        {days.map((d) => (
          <div key={isoDate(d)} className="cal-allday" onClick={() => onCreate(d, true)}>
            {(byDay.get(isoDate(d)) ?? []).filter((i) => !isTimed(i)).map((i) => <Ev key={i.id} i={i} onOpen={onOpen} />)}
          </div>
        ))}
      </div>
      <div ref={scroller} style={{ maxHeight: 620, overflowY: 'auto' }}>
        <div className={`cal-week ${days.length === 1 ? 'day' : ''}`}>
          <div>{Array.from({ length: 24 }, (_, h) => <div key={h} className="cal-hour">{String(h).padStart(2, '0')}:00</div>)}</div>
          {days.map((d) => {
            const dayStart = new Date(d.getFullYear(), d.getMonth(), d.getDate())
            const dayEnd = addDays(dayStart, 1)
            const list = timed.filter((i) => { const s = startOf(i); const e = i.end ? new Date(i.end) : s; return s < dayEnd && e >= dayStart })
            return (
              <div key={isoDate(d)} className="cal-col">
                {Array.from({ length: 24 }, (_, h) => <div key={h} className="slot" onClick={() => onCreate(new Date(d.getFullYear(), d.getMonth(), d.getDate(), h), false)} />)}
                {list.map((i, idx) => {
                  const s = new Date(Math.max(startOf(i).getTime(), dayStart.getTime()))
                  const e = new Date(Math.min((i.end ? new Date(i.end) : new Date(startOf(i).getTime() + 3600_000)).getTime(), dayEnd.getTime()))
                  const top = ((s.getTime() - dayStart.getTime()) / 3600_000) * HOUR_PX
                  const height = Math.max(22, ((e.getTime() - s.getTime()) / 3600_000) * HOUR_PX - 2)
                  return (
                    <div key={i.id} className={`cal-timed cat-${i.category}`} style={{ top, height, left: 3 + (idx % 3) * 6 }} title={i.title} role="button" tabIndex={0}
                      onClick={() => onOpen(i)} onKeyDown={(ev) => ev.key === 'Enter' && onOpen(i)}>
                      <b>{startOf(i).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</b> {i.title}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function YearView({ year, byDay, onDay, onMonth }: { year: number; byDay: Map<string, Item[]>; onDay: (d: Date) => void; onMonth: (m: number) => void }) {
  const today = new Date()
  return (
    <div className="cal-year">
      {MONTHS.map((name, m) => {
        const first = new Date(year, m, 1)
        const lead = (first.getDay() + 6) % 7
        const days = new Date(year, m + 1, 0).getDate()
        const count = Array.from({ length: days }, (_, i) => byDay.get(isoDate(new Date(year, m, i + 1)))?.length ?? 0).reduce((a, b) => a + b, 0)
        return (
          <div key={m} className="mini-month">
            <h4 onClick={() => onMonth(m)}>{name} <span className="muted small">{count ? `· ${count}` : ''}</span></h4>
            <div className="mini-grid">
              {DOW.map((d) => <span key={d} className="dow">{d[0]}</span>)}
              {Array.from({ length: lead }, (_, i) => <span key={`l${i}`} style={{ cursor: 'default' }} />)}
              {Array.from({ length: days }, (_, i) => {
                const d = new Date(year, m, i + 1)
                const n = byDay.get(isoDate(d))?.length ?? 0
                return <span key={i} className={`${n ? 'has' : ''} ${sameDay(d, today) ? 'today' : ''}`} title={n ? `${n} item(s)` : undefined} onClick={() => onDay(d)}>{i + 1}</span>
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const pad = (n: number) => String(n).padStart(2, '0')
const timeStr = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`

function EventForm({ item, start, allDay, onClose }: { item?: Item; start?: Date; allDay?: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const confirm = useConfirm()
  const projects = useProjectOptions()
  const s0 = item ? new Date(item.start) : start ?? new Date()
  const e0 = item?.end ? new Date(item.end) : new Date(s0.getTime() + 3600_000)
  const lim = limits()
  const f = useForm({
    title: item?.title ?? '', event_type: item?.category && EVENT_TYPES.includes(item.category) ? item.category : 'meeting', description: item?.description ?? '',
    all_day: item ? item.all_day : !!allDay, start_date: isoDate(s0), start_time: timeStr(s0), end_date: isoDate(e0), end_time: timeStr(e0),
    location: item?.location ?? '', project_id: item?.project_id ? String(item.project_id) : '', remind: item?.remind_minutes_before != null ? String(item.remind_minutes_before) : '',
  })
  const v = f.values
  const toDate = (d: string, t: string, endOfDay = false) => {
    const [y, m, day] = d.split('-').map(Number)
    if (v.all_day) return endOfDay ? new Date(y, m - 1, day, 23, 59) : new Date(y, m - 1, day, 0, 0)
    const [hh, mm] = t.split(':').map(Number)
    return new Date(y, m - 1, day, hh, mm)
  }
  const sd = v.start_date ? toDate(v.start_date, v.start_time) : null
  const ed = v.end_date ? toDate(v.end_date, v.end_time, true) : null
  const rangeErr = sd && (sd < lim.min || sd > lim.max) ? `Dates must be within ±${YEARS_RANGE} years` : undefined
  const orderErr = sd && ed && ed < sd ? 'End must be after the start' : undefined
  const save = () => f.submit(async () => {
    const body = {
      title: v.title, event_type: v.event_type, description: v.description || null, all_day: v.all_day,
      start_at: sd!.toISOString(), end_at: ed ? ed.toISOString() : null, location: v.location || null,
      project_id: Number(v.project_id) || null, remind_minutes_before: v.remind === '' ? null : Number(v.remind),
    }
    if (item) await api.patch(`/api/calendar/events/${item.source_id}`, body)
    else await api.post('/api/calendar/events', body)
    toast(item ? 'Event updated' : 'Event created')
    qc.invalidateQueries({ queryKey: ['calendar'] })
    onClose()
  }).catch(() => {})
  const remove = async () => {
    if (!(await confirm({ title: 'Delete event?', message: `"${item!.title}" will be deleted.`, danger: true, confirmText: 'Delete' }))) return
    try {
      await api.del(`/api/calendar/events/${item!.source_id}`)
      toast('Event deleted')
      qc.invalidateQueries({ queryKey: ['calendar'] })
      onClose()
    } catch (e) { toast(errorMessage(e), 'error') }
  }
  return (
    <Modal title={item ? 'Edit event' : 'New event'} onClose={onClose}
      footer={<>{item && <button className="btn danger" style={{ marginRight: 'auto' }} onClick={remove}><Trash2 size={14} /> Delete</button>}
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={f.submitting || !v.title.trim() || !sd || !!rangeErr || !!orderErr} onClick={save}>{f.submitting ? 'Saving…' : 'Save event'}</button></>}>
      <div className="form">
        {f.formError && <Alert kind="danger">{f.formError}</Alert>}
        <div className="form-grid">
          <Field label="Title" required className="span-2" error={f.errors.title}><input className="input" value={v.title} onChange={(e) => f.set('title', e.target.value)} /></Field>
          <Field label="Type"><Select value={v.event_type} onChange={(x) => f.set('event_type', x)} options={EVENT_TYPES.map((t) => ({ value: t, label: label(t) }))} /></Field>
          <label className="checkbox" style={{ alignSelf: 'end' }}><input type="checkbox" checked={v.all_day} onChange={(e) => f.set('all_day', e.target.checked)} /> All day</label>
          <Field label="Start date" required error={rangeErr}><input type="date" className="input" min={isoDate(lim.min)} max={isoDate(lim.max)} value={v.start_date} onChange={(e) => f.set('start_date', e.target.value)} /></Field>
          {!v.all_day ? <Field label="Start time"><input type="time" className="input" value={v.start_time} onChange={(e) => f.set('start_time', e.target.value)} /></Field> : <div />}
          <Field label="End date" error={orderErr}><input type="date" className="input" min={isoDate(lim.min)} max={isoDate(lim.max)} value={v.end_date} onChange={(e) => f.set('end_date', e.target.value)} /></Field>
          {!v.all_day ? <Field label="End time"><input type="time" className="input" value={v.end_time} onChange={(e) => f.set('end_time', e.target.value)} /></Field> : <div />}
          <Field label="Project"><Select value={v.project_id} onChange={(x) => f.set('project_id', x)} options={projects.data ?? []} placeholder="None (personal)" /></Field>
          <Field label="Location"><input className="input" value={v.location} onChange={(e) => f.set('location', e.target.value)} /></Field>
          <Field label="Reminder" hint="Delivered as an in-app notification (and email if configured)">
            <Select value={v.remind} onChange={(x) => f.set('remind', x)} placeholder="No reminder" options={[
              { value: '0', label: 'At start time' }, { value: '15', label: '15 minutes before' }, { value: '60', label: '1 hour before' },
              { value: '1440', label: '1 day before' }, { value: '10080', label: '1 week before' },
            ]} /></Field>
          <div />
          <Field label="Description" className="span-2"><textarea className="input" value={v.description} onChange={(e) => f.set('description', e.target.value)} /></Field>
        </div>
        <p className="small muted">Events without a project are visible only to you and managers. Project events are visible to the project team.</p>
      </div>
    </Modal>
  )
}
