import { Link } from 'react-router'
import ApiStatus from '../components/ApiStatus'

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-3xl font-bold">Application Tracker</h1>
      <p className="mt-4 text-gray-700">
        Connect Gmail, see every internship application with its status, and get follow-up drafts
        and a daily digest.
      </p>
      <div className="mt-8 flex gap-4">
        <Link to="/demo" className="rounded bg-gray-900 px-4 py-2 text-white">
          Try the demo
        </Link>
      </div>
      <div className="mt-8">
        <ApiStatus />
      </div>
      <footer className="mt-12 border-t pt-4 text-sm">
        <Link to="/privacy" className="link">
          Privacy
        </Link>
      </footer>
    </main>
  )
}
