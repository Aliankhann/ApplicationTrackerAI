import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ErrorState, LoadingSkeleton } from '../components/QueryStates'
import {
  reasonText,
  relativeDate,
  shortDate,
  statusLabel,
  suggestionLabel,
} from '../components/format'
import { useBasePath } from '../data/context'
import { ApiError } from '../data/dataSource'
import {
  useApplication,
  useConfirmApplication,
  useDismissApplication,
  useEvents,
  useUpdateApplication,
} from '../data/hooks'
import {
  COMPANY_MAX,
  ROLE_MAX,
  STATUSES,
  validateText,
  type ApplicationDetail,
  type Status,
} from '../data/schemas'
import SignInRequired from './SignInRequired'

type Update = ReturnType<typeof useUpdateApplication>

function EditDetails({
  app,
  update,
  onDone,
}: {
  app: ApplicationDetail
  update: Update
  onDone: () => void
}) {
  const [company, setCompany] = useState(app.company ?? '')
  const [role, setRole] = useState(app.role ?? '')
  const [errors, setErrors] = useState<{ company?: string; role?: string }>({})

  const save = (event: React.FormEvent) => {
    event.preventDefault()
    const next = {
      company: validateText(company, COMPANY_MAX, 'Company') ?? undefined,
      role: validateText(role, ROLE_MAX, 'Role') ?? undefined,
    }
    setErrors(next)
    if (next.company || next.role) return
    // Stay open until the save succeeds so typed values survive a failure.
    update.mutate({ company: company.trim(), role: role.trim() }, { onSuccess: onDone })
  }

  return (
    <form onSubmit={save} className="space-y-3" aria-label="Edit details">
      <div>
        <label htmlFor="company" className="block text-sm">
          Company
        </label>
        <input
          id="company"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          className="field w-full"
          aria-invalid={!!errors.company}
          aria-describedby="company-error"
        />
        {errors.company && (
          <p id="company-error" role="alert" className="text-sm text-red-800 dark:text-red-300">
            {errors.company}
          </p>
        )}
      </div>
      <div>
        <label htmlFor="role" className="block text-sm">
          Role
        </label>
        <input
          id="role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="field w-full"
          aria-invalid={!!errors.role}
          aria-describedby="role-error"
        />
        {errors.role && (
          <p id="role-error" role="alert" className="text-sm text-red-800 dark:text-red-300">
            {errors.role}
          </p>
        )}
      </div>
      <div className="flex gap-2">
        <button type="submit" className="btn">
          Save
        </button>
        <button type="button" className="btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </form>
  )
}

function ReviewPanel({ app }: { app: ApplicationDetail }) {
  const confirm = useConfirmApplication(app.id)
  const dismiss = useDismissApplication(app.id)
  const navigate = useNavigate()
  const base = useBasePath()
  const suggestion = suggestionLabel(app.suggested_label)
  const busy = confirm.isPending || dismiss.isPending
  return (
    <section
      role="note"
      aria-label="Needs review"
      className="mt-4 rounded border border-amber-500 p-3"
    >
      <p>
        Needs review: this looks like a job email, but its status could not be decided.
        {suggestion ? ` Suggested status: ${suggestion}.` : ' There is no suggestion.'}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {suggestion && (
          <button type="button" className="btn" disabled={busy} onClick={() => confirm.mutate()}>
            Confirm {suggestion}
          </button>
        )}
        <span className="text-sm">Or pick a status with Change status below.</span>
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => dismiss.mutate(undefined, { onSuccess: () => void navigate(base) })}
        >
          Dismiss
        </button>
      </div>
      {(confirm.isError || dismiss.isError) && (
        <p role="alert" className="mt-2 text-red-800 dark:text-red-300">
          Could not complete that. Nothing was changed.
        </p>
      )}
    </section>
  )
}

function Timeline({ id }: { id: string }) {
  const events = useEvents(id)
  if (events.isPending) return <LoadingSkeleton label="Loading timeline" />
  if (events.isError)
    return (
      <ErrorState message="Could not load the timeline." onRetry={() => void events.refetch()} />
    )
  const ordered = [...events.data].sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
  return (
    <ol className="space-y-2">
      {ordered.map((e) => (
        <li key={`${e.at}-${e.to_status}`}>
          <span className="font-medium">
            {e.from_status ? `${statusLabel(e.from_status)} → ` : ''}
            {statusLabel(e.to_status)}
          </span>{' '}
          <span className="text-sm text-gray-700 dark:text-gray-300">
            ({reasonText(e.reason)}, {shortDate(e.at)})
          </span>
        </li>
      ))}
    </ol>
  )
}

function Detail({ app }: { app: ApplicationDetail }) {
  const update = useUpdateApplication(app.id)
  const [editing, setEditing] = useState(false)
  return (
    <>
      <h1 className="text-2xl font-bold">{app.company ?? 'Unknown company'}</h1>
      <p className="text-gray-700 dark:text-gray-300">{app.role ?? 'Role not detected'}</p>

      {app.needs_review && <ReviewPanel app={app} />}
      {update.isError && (
        <p
          role="alert"
          className="mt-4 rounded border border-red-400 p-3 text-red-800 dark:text-red-300"
        >
          Could not save your change. It has been reverted.
        </p>
      )}

      <dl className="mt-6 grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
        <dt className="font-medium">Status</dt>
        <dd>
          <span className="mr-2">{statusLabel(app.display_status)}</span>
          <label className="text-sm">
            Change status{' '}
            <select
              className="field"
              disabled={update.isPending}
              value={app.needs_review ? '' : app.status}
              onChange={(e) => update.mutate({ status: e.target.value as Status })}
            >
              {app.needs_review && (
                <option value="" disabled>
                  Choose a status
                </option>
              )}
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </select>
          </label>
          {app.status_locked && <p className="text-sm">Locked: you set this manually</p>}
        </dd>
        <dt className="font-medium">Applied</dt>
        <dd>{shortDate(app.applied_at)}</dd>
        <dt className="font-medium">Last activity</dt>
        <dd>{relativeDate(app.last_activity_at)}</dd>
        <dt className="font-medium">Follow-ups</dt>
        <dd>
          <button
            type="button"
            className="btn"
            disabled={update.isPending}
            aria-pressed={app.followups_paused}
            onClick={() => update.mutate({ followups_paused: !app.followups_paused })}
          >
            {app.followups_paused ? 'Resume follow-ups' : 'Pause follow-ups'}
          </button>
          {app.followups_paused && <span className="ml-2 text-sm">Follow-ups paused</span>}
        </dd>
      </dl>

      <section className="mt-8" aria-labelledby="edit-h">
        <h2 id="edit-h" className="mb-2 text-lg font-semibold">
          Details
        </h2>
        {editing ? (
          <EditDetails app={app} update={update} onDone={() => setEditing(false)} />
        ) : (
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            Edit company and role
          </button>
        )}
      </section>

      <section className="mt-8" aria-labelledby="email-h">
        <h2 id="email-h" className="mb-2 text-lg font-semibold">
          Email
        </h2>
        <blockquote className="border-l-4 border-gray-400 pl-4">
          <p className="font-medium">{app.subject ?? 'No subject'}</p>
          <p className="text-gray-700 dark:text-gray-300">{app.snippet ?? ''}</p>
        </blockquote>
      </section>

      <section className="mt-8" aria-labelledby="timeline-h">
        <h2 id="timeline-h" className="mb-2 text-lg font-semibold">
          Timeline
        </h2>
        <Timeline id={app.id} />
      </section>
    </>
  )
}

export default function ApplicationDetailPage() {
  const { id = '' } = useParams()
  const base = useBasePath()
  const query = useApplication(id)

  let content
  if (query.error instanceof ApiError && query.error.status === 401) return <SignInRequired />
  if (query.isPending) content = <LoadingSkeleton label="Loading application" />
  else if (query.error instanceof ApiError && query.error.status === 404) {
    content = (
      <>
        <h1 className="text-2xl font-bold">Application not found</h1>
        <p className="mt-2">
          <Link to={base} className="link">
            Back to applications
          </Link>
        </p>
      </>
    )
  } else if (query.isError) {
    content = (
      <ErrorState message="Could not load this application." onRetry={() => void query.refetch()} />
    )
  } else content = <Detail app={query.data} />

  return (
    <main className="mx-auto max-w-3xl px-4 py-8">
      {query.isSuccess && (
        <p className="mb-4">
          <Link to={base} className="link">
            ← Back to applications
          </Link>
        </p>
      )}
      {content}
    </main>
  )
}
