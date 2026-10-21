import { PageHead } from '../components/Layout'
import { UpdatesFeed } from '../components/updates'

export default function UpdatesPage() {
  return (
    <>
      <PageHead title="Updates" sub="Timestamped progress updates from every project. Corrections keep the original as a revision." />
      <UpdatesFeed />
    </>
  )
}
