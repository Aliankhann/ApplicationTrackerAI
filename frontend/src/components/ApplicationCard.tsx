import { Link } from 'react-router'
import type { Application } from '../data/schemas'
import { useBasePath } from '../data/context'
import { relativeDate, suggestionLabel } from './format'

export function Badges({ app }: { app: Application }) {
  return (
    <>
      {app.needs_review && <span className="badge badge-warn">Needs review</span>}
      {app.needs_review && suggestionLabel(app.suggested_label) && (
        <span className="badge">Suggested: {suggestionLabel(app.suggested_label)}</span>
      )}
      {app.followups_paused && <span className="badge">Follow-ups paused</span>}
    </>
  )
}

export function ApplicationCard({ app }: { app: Application }) {
  const base = useBasePath()
  return (
    <li>
      <Link to={`${base}/applications/${app.id}`} className="card">
        <span className="block font-medium">{app.company ?? 'Unknown company'}</span>
        <span className="block text-sm text-gray-700 dark:text-gray-300">
          {app.role ?? 'Role not detected'}
        </span>
        <span className="mt-1 block text-xs text-gray-600 dark:text-gray-400">
          Last activity {relativeDate(app.last_activity_at)}
        </span>
        <span className="mt-2 flex flex-wrap gap-1">
          <Badges app={app} />
        </span>
      </Link>
    </li>
  )
}
