import { PageHead } from '../components/Layout'
import { ReportsPanel } from '../components/reports'

export default function ReportsPage() {
  return (
    <>
      <PageHead title="Status Reports" sub="Weekly, monthly, quarterly, annual and custom reports generated from live records." />
      <ReportsPanel />
    </>
  )
}
