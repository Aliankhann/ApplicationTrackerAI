import { useState } from 'react'
import { ApplicationTable } from '../components/ApplicationTable'
import { Board } from '../components/Board'
import { EmptyState, ErrorState, LoadingSkeleton } from '../components/QueryStates'
import { statusLabel } from '../components/format'
import { ApiError } from '../data/dataSource'
import { useApplications } from '../data/hooks'
import { FILTER_STATUSES, type FilterStatus, type ListParams } from '../data/schemas'
import SignInRequired from './SignInRequired'

type View = 'board' | 'table'
const VIEW_KEY = 'tracker:view'

function loadView(): View {
  try {
    return localStorage.getItem(VIEW_KEY) === 'table' ? 'table' : 'board'
  } catch {
    return 'board'
  }
}

function saveView(view: View) {
  try {
    localStorage.setItem(VIEW_KEY, view)
  } catch {
    // Storage can be blocked; the choice just won't persist.
  }
}

const SORTS = {
  'last_activity:desc': 'Last activity (newest first)',
  'last_activity:asc': 'Last activity (oldest first)',
  'applied_at:desc': 'Applied (newest first)',
  'applied_at:asc': 'Applied (oldest first)',
} as const
type SortChoice = keyof typeof SORTS

function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div role="radiogroup" aria-label="Dashboard view" className="flex gap-2">
      {(['board', 'table'] as const).map((v) => (
        <label key={v} className={`btn cursor-pointer ${view === v ? 'btn-on' : ''}`}>
          <input
            type="radio"
            name="view"
            value={v}
            checked={view === v}
            onChange={() => onChange(v)}
            aria-label={`${v === 'board' ? 'Board' : 'Table'} view`}
            className="sr-only"
          />
          {v === 'board' ? 'Board' : 'Table'}
        </label>
      ))}
    </div>
  )
}

export default function DashboardPage() {
  const [view, setView] = useState<View>(loadView)
  const [sort, setSort] = useState<SortChoice>('last_activity:desc')
  const [status, setStatus] = useState<FilterStatus | ''>('')

  const params: Omit<ListParams, 'cursor'> = {}
  if (view === 'table') {
    const [field, order] = sort.split(':') as [ListParams['sort'], ListParams['order']]
    Object.assign(params, {
      sort: field,
      order,
      ...(status ? { status } : {}),
    })
  }
  const query = useApplications(params)

  const changeView = (next: View) => {
    setView(next)
    saveView(next)
  }

  if (query.error instanceof ApiError && query.error.status === 401) return <SignInRequired />

  const items = query.data?.pages.flatMap((p) => p.items) ?? []

  let content
  if (query.isPending) content = <LoadingSkeleton label="Loading applications" />
  else if (query.isError)
    content = (
      <ErrorState message="Could not load applications." onRetry={() => void query.refetch()} />
    )
  else if (items.length === 0 && !status) content = <EmptyState demoPath="/demo" />
  else if (view === 'board') content = <Board items={items} hasMore={query.hasNextPage} />
  else content = <ApplicationTable items={items} />

  return (
    <main className="mx-auto max-w-7xl px-4 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-bold">Applications</h1>
        <ViewToggle view={view} onChange={changeView} />
      </div>
      {view === 'table' && (
        <div className="mb-4 flex flex-wrap gap-4">
          <label className="text-sm">
            Sort by{' '}
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value as SortChoice)}
              className="field"
            >
              {Object.entries(SORTS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            Filter by status{' '}
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as FilterStatus | '')}
              className="field"
            >
              <option value="">All statuses</option>
              {FILTER_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {statusLabel(s)}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      {content}
      {query.hasNextPage && (
        <button
          type="button"
          className="btn mt-6"
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
        >
          {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
        </button>
      )}
    </main>
  )
}
