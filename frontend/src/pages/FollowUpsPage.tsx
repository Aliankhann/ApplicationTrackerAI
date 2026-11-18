import { ErrorState, LoadingSkeleton } from '../components/QueryStates'
import { useFollowUpAction, useFollowUps } from '../data/hooks'
import type { FollowUp } from '../data/schemas'

const DELAY_DAYS = 3

function dueText(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function Title({ item }: { item: FollowUp }) {
  return (
    <div>
      <p className="font-medium">{item.company ?? 'Unknown company'}</p>
      <p className="text-sm text-gray-700 dark:text-gray-300">
        {item.role ?? 'Role not detected'} · Step {item.step_index + 1}
      </p>
    </div>
  )
}

function ScheduledRow({ item }: { item: FollowUp }) {
  const skip = useFollowUpAction(item.id, 'skip')
  const delay = useFollowUpAction(item.id, 'delay', DELAY_DAYS)
  const failed = skip.isError || delay.isError
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 rounded border p-3">
      <Title item={item} />
      <p className="text-sm">Due {dueText(item.due_at)}</p>
      <div className="flex gap-2">
        <button type="button" className="btn" onClick={() => skip.mutate()}>
          Skip
        </button>
        <button type="button" className="btn" onClick={() => delay.mutate()}>
          Delay {DELAY_DAYS} days
        </button>
      </div>
      {failed && (
        <p role="alert" className="w-full text-sm text-red-800 dark:text-red-300">
          Could not update this follow-up for {item.company ?? 'this application'}. The change was
          reverted.
        </p>
      )}
    </li>
  )
}

function DraftRow({ item }: { item: FollowUp }) {
  return (
    <li className="rounded border p-3">
      <Title item={item} />
      <p className="mt-1 text-sm">Open Gmail to review and send.</p>
    </li>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <ul className="mt-2 space-y-2">{children}</ul>
    </section>
  )
}

export default function FollowUpsPage() {
  const query = useFollowUps()
  const items = query.data ?? []
  const drafted = items.filter((t) => t.state === 'drafted')
  const pending = items.filter((t) => t.state === 'pending')
  return (
    <main className="mx-auto max-w-3xl p-4">
      <h1 className="text-2xl font-bold">Follow-ups</h1>
      {query.isPending && <LoadingSkeleton label="Loading follow-ups" />}
      {query.isError && (
        <ErrorState message="Could not load follow-ups." onRetry={() => void query.refetch()} />
      )}
      {query.isSuccess && items.length === 0 && (
        <p className="mt-6 rounded border border-dashed p-6 text-center">
          No upcoming follow-ups. They appear here after you apply and hear nothing back.
        </p>
      )}
      {drafted.length > 0 && (
        <Group title="Drafts waiting for you">
          {drafted.map((t) => (
            <DraftRow key={t.id} item={t} />
          ))}
        </Group>
      )}
      {pending.length > 0 && (
        <Group title="Scheduled">
          {pending.map((t) => (
            <ScheduledRow key={t.id} item={t} />
          ))}
        </Group>
      )}
    </main>
  )
}
