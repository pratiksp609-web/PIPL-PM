import { useSearchParams } from 'react-router-dom'
import { PageHead } from '../components/Layout'
import { TasksPanel } from '../components/tasks'

export default function TasksPage() {
  const [sp] = useSearchParams()
  const initial: Record<string, string | boolean> = {}
  if (sp.get('mine') === '1') initial.mine = true
  if (sp.get('overdue') === '1') initial.overdue = true
  if (sp.get('status')) initial.status = sp.get('status')!
  const taskId = Number(sp.get('task')) || null
  return (
    <>
      <PageHead title="To-Do List" sub="Tasks across all projects, with assignees, priorities, due dates and progress." />
      <TasksPanel key={sp.toString()} initialFilters={initial} openTaskId={taskId} />
    </>
  )
}
