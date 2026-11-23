import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useDataSource } from '../data/context'
import { useConnectGmail, useGmailStatus, useSync } from '../data/hooks'
import { syncErrorMessage } from './gmailText'

function ConnectCard({ demo }: { demo: boolean }) {
  const connect = useConnectGmail()
  return (
    <section aria-labelledby="connect-gmail" className="mb-6 rounded border p-4">
      <h2 id="connect-gmail" className="text-lg font-bold">
        Connect Gmail
      </h2>
      <p className="mt-2 text-sm">
        We read only the sender, subject, and a short snippet of job-related email from the last 90
        days to build this list. We never store full emails, and we never send anything. You can
        disconnect and delete the synced data at any time.{' '}
        <Link to="/privacy" className="link">
          What we read and store
        </Link>
      </p>
      {demo && <p className="mt-2 text-sm">Gmail is not available in the demo.</p>}
      {connect.isError && (
        <p role="alert" className="mt-2 text-sm text-red-800 dark:text-red-300">
          Could not start the connection. Please try again.
        </p>
      )}
      <button
        type="button"
        className="btn mt-3"
        disabled={demo || connect.isPending}
        onClick={() => connect.mutate(false)}
      >
        Connect Gmail
      </button>
    </section>
  )
}

function lastSyncedText(iso: string | null): string {
  return iso ? `Last synced ${new Date(iso).toLocaleString()}.` : 'Not synced yet.'
}

function SyncCard({ connectedParam }: { connectedParam: boolean }) {
  const [justConnected] = useState(connectedParam) // the URL param is removed right away
  const { query, running, start } = useSync(true)
  const started = useRef(false)
  const [, setParams] = useSearchParams()
  const startSync = start.mutate
  useEffect(() => {
    if (!justConnected || started.current) return
    started.current = true
    startSync()
    setParams({}, { replace: true }) // a refresh must not start another sync
  }, [justConnected, startSync, setParams])
  const data = query.data
  const failed = start.isError
  return (
    <section aria-labelledby="sync-heading" className="mb-6 rounded border p-4">
      <h2 id="sync-heading" className="text-lg font-bold">
        Gmail sync
      </h2>
      {justConnected && (
        <p role="status" className="mt-2 text-sm">
          Gmail is connected. Your first sync is starting.
        </p>
      )}
      <p aria-live="polite" className="mt-2 text-sm">
        {running ? 'Syncing your email…' : data ? lastSyncedText(data.last_synced_at) : ''}
      </p>
      {!running && data?.last_error && (
        <p role="alert" className="mt-1 text-sm text-red-800 dark:text-red-300">
          {syncErrorMessage(data.last_error)}
        </p>
      )}
      {failed && (
        <p role="alert" className="mt-1 text-sm text-red-800 dark:text-red-300">
          Could not run a sync. You can try a few times an hour; please wait and try again.
        </p>
      )}
      {start.data?.status === 'in_progress' && (
        <p role="status" className="mt-1 text-sm">
          Part of your email is synced. The rest continues at the next daily update, or press Sync
          now again.
        </p>
      )}
      <p className="mt-1 text-sm">
        Gmail updates once a day. Press Sync now for fresher data.
      </p>
      <button
        type="button"
        className="btn mt-3"
        disabled={running || start.isPending}
        onClick={() => start.mutate()}
      >
        Sync now
      </button>
    </section>
  )
}

export function GmailPanel() {
  const demo = useDataSource().kind === 'demo'
  const status = useGmailStatus()
  const [params] = useSearchParams()
  if (status.isPending) return null
  if (status.data?.connected) return <SyncCard connectedParam={params.get('connected') === '1'} />
  return <ConnectCard demo={demo} />
}
