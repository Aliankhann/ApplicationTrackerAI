import type { Application } from '../data/schemas'
import { ApplicationCard } from './ApplicationCard'
import { BOARD_COLUMNS, statusLabel } from './format'

const OTHER = 'other'
const isKnown = (value: string) => (BOARD_COLUMNS as readonly string[]).includes(value)

// display_status first, then status, then "Other" so no card is ever dropped.
function columnFor(app: Application): string {
  if (isKnown(app.display_status)) return app.display_status
  return isKnown(app.status) ? app.status : OTHER
}

export function Board({ items, hasMore = false }: { items: Application[]; hasMore?: boolean }) {
  const other = items.filter((a) => columnFor(a) === OTHER)
  const columns = other.length > 0 ? [...BOARD_COLUMNS, OTHER] : BOARD_COLUMNS
  return (
    <div className="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      {columns.map((status) => {
        const column = items.filter((a) => columnFor(a) === status)
        const count = hasMore ? `${column.length}+` : String(column.length)
        return (
          <section key={status} aria-labelledby={`col-${status}`}>
            <h2 id={`col-${status}`} className="mb-2 font-semibold">
              {status === OTHER ? 'Other' : statusLabel(status)}{' '}
              <span className="text-gray-600 dark:text-gray-400">({count})</span>
            </h2>
            <ul className="space-y-2">
              {column.map((app) => (
                <ApplicationCard key={app.id} app={app} />
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
