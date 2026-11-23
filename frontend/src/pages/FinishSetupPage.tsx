import { useSearchParams } from 'react-router'
import { Link } from 'react-router'
import { connectErrorMessage } from '../components/gmailText'
import { useConnectGmail } from '../data/hooks'
import type { Me } from '../data/schemas'

// Shown instead of the app until the invited user has connected Gmail: that completes sign-up.
export default function FinishSetupPage({ me }: { me: Me }) {
  const connect = useConnectGmail()
  const [params] = useSearchParams()
  const errorCode = params.get('gmail_error')
  const until = me.invite_held_until ? new Date(me.invite_held_until).toLocaleString() : null
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Finish setup: connect Gmail</h1>
      <p className="mt-4 text-gray-700 dark:text-gray-300">
        You are signed in. To finish creating your account, connect Gmail. We read only the sender,
        subject, and a short snippet of job-related email from the last 90 days. We never store full
        emails and never send anything.{' '}
        <Link to="/privacy" className="link">
          What we read and store
        </Link>
      </p>
      {until && (
        <p className="mt-4 text-sm" role="status">
          Your invite is held until {until}. After that it is released and this unfinished account
          is removed.
        </p>
      )}
      {errorCode && (
        <p role="alert" className="mt-4 text-red-800 dark:text-red-300">
          {connectErrorMessage(errorCode)}
        </p>
      )}
      {connect.isError && (
        <p role="alert" className="mt-4 text-red-800 dark:text-red-300">
          Could not start the connection. Please try again.
        </p>
      )}
      <button
        type="button"
        className="btn mt-6"
        disabled={connect.isPending}
        onClick={() => connect.mutate(false)}
      >
        Connect Gmail
      </button>
    </main>
  )
}
