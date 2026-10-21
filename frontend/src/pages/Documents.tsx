import { PageHead } from '../components/Layout'
import { DocumentsPanel } from '../components/documents'

export default function DocumentsPage() {
  return (
    <>
      <PageHead title="Documents" sub="Quotations, purchase orders, invoices, drawings, reports and other project files, with version history." />
      <DocumentsPanel />
    </>
  )
}
