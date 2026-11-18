import { Link, useLocation } from 'react-router'
import { RemoveAccessLink } from '../components/DataControls'
import { BACKUP_RETENTION_DAYS } from '../constants'

export default function GoodbyePage() {
  const state = useLocation().state as {
    revokedAtGoogle?: boolean | null
  } | null
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Your account and data were deleted</h1>
      <p className="mt-3">
        We deleted your account, applications, follow-ups, settings, and any synced email data, and
        signed you out.
      </p>
      {state?.revokedAtGoogle === false && (
        <p role="alert" className="mt-3">
          We could not revoke our access at Google. <RemoveAccessLink /> to be sure.
        </p>
      )}
      <p className="mt-3">
        {BACKUP_RETENTION_DAYS === null
          ? "Database backups expire on the host's schedule. [TODO: state the retention window once hosting is chosen.]"
          : `Backups expire within ${BACKUP_RETENTION_DAYS} days.`}
      </p>
      <Link to="/" className="mt-4 inline-block underline">
        Back home
      </Link>
    </main>
  )
}
