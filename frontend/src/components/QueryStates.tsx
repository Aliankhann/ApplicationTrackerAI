import { Link } from 'react-router'

export function LoadingSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded bg-gray-200 dark:bg-gray-800" />
        ))}
      </div>
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="rounded border border-red-300 p-4 dark:border-red-700">
      <p className="text-red-800 dark:text-red-300">{message}</p>
      <button type="button" onClick={onRetry} className="btn mt-3">
        Retry
      </button>
    </div>
  )
}

export function EmptyState({ demoPath }: { demoPath: string }) {
  return (
    <section className="rounded border border-dashed border-gray-400 p-8 text-center">
      <h2 className="text-lg font-semibold">No applications yet</h2>
      <p className="mt-2 text-gray-700 dark:text-gray-300">
        Run a sync to find applications in your Gmail, or{' '}
        <Link to={demoPath} className="link">
          explore the demo
        </Link>
        .
      </p>
    </section>
  )
}
