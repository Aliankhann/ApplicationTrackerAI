import { Link } from 'react-router'
import { DataControls } from '../components/DataControls'
import { DigestToggle } from '../components/DigestToggle'
import { useBasePath } from '../data/context'

export default function SettingsPage() {
  const basePath = useBasePath()
  return (
    <main className="mx-auto max-w-2xl px-4 py-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      <ul className="mt-4 list-disc pl-5">
        <li>
          <Link to={`${basePath}/settings/follow-ups`} className="link">
            Follow-up settings
          </Link>
        </li>
      </ul>
      <DigestToggle />
      <DataControls />
    </main>
  )
}
