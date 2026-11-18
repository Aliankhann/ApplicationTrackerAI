import {
  buildDemoFollowUps,
  buildDemoRecords,
  buildDemoSequences,
  type DemoRecord,
} from '../demo/data'
import { renderPreview } from '../demo/preview'
import { ApiError, type DataSource } from './dataSource'
import type { ApplicationDetail, FollowUp, ListParams, Sequence } from './schemas'
import { validateSteps, validateTemplate } from './sequenceValidation'

const DEFAULT_LIMIT = 50

function sortKey(record: DemoRecord, sort: ListParams['sort']): number {
  const { detail } = record
  const value = sort === 'applied_at' ? detail.applied_at : detail.last_activity_at
  return value ? Date.parse(value) : 0
}

// In-memory only: never touches the network. Each instance starts from the seeded dataset.
export function createDemoDataSource(now: Date = new Date()): DataSource {
  const records = buildDemoRecords(now)
  let followUps = buildDemoFollowUps(now, records)
  let sequences = buildDemoSequences()

  const findFollowUp = (id: string): FollowUp => {
    const task = followUps.find((t) => t.id === id)
    if (!task) throw new ApiError(404, 'Not found')
    return task
  }
  const requirePending = (id: string): FollowUp => {
    const task = findFollowUp(id)
    if (task.state !== 'pending') throw new ApiError(409, 'Not pending')
    return task
  }
  const replaceFollowUp = (next: FollowUp): FollowUp => {
    followUps = followUps.map((t) => (t.id === next.id ? next : t))
    return { ...next }
  }
  const checkSequence = (steps: Sequence['steps'] | undefined) => {
    const errors = steps ? validateSteps(steps) : []
    if (errors.length) throw new ApiError(422, 'Invalid sequence', errors)
  }
  const replaceSequence = (next: Sequence): Sequence => {
    sequences = sequences.map((s) =>
      s.id === next.id ? next : next.is_default ? { ...s, is_default: false } : s,
    )
    return { ...next }
  }

  const find = (id: string): DemoRecord => {
    const record = records.find((r) => r.detail.id === id)
    if (!record) throw new ApiError(404, 'Not found')
    return record
  }

  return {
    kind: 'demo',
    async listApplications(params) {
      const { status, sort = 'last_activity', order = 'desc', limit = DEFAULT_LIMIT } = params
      const direction = order === 'desc' ? -1 : 1
      const rows = records
        .filter((r) => !status || r.detail.display_status === status)
        .sort((a, b) => direction * (sortKey(a, sort) - sortKey(b, sort)))
      const start = params.cursor ? Number(params.cursor) : 0
      const page = rows.slice(start, start + limit)
      const next = start + limit < rows.length ? String(start + limit) : null
      return {
        items: page.map(({ detail: { subject: _s, snippet: _n, ...item } }) => item),
        next_cursor: next,
      }
    },
    async getApplication(id) {
      return { ...find(id).detail }
    },
    async listEvents(id) {
      return [...find(id).events]
    },
    async updateApplication(id, patch) {
      const record = find(id)
      const previous = record.detail
      const next: ApplicationDetail = { ...previous, ...patch }
      if (patch.status && patch.status !== previous.status) {
        next.display_status = patch.status
        next.status_locked = true
        record.events = [
          ...record.events,
          {
            from_status: previous.status,
            to_status: patch.status,
            reason: 'manual',
            at: new Date().toISOString(),
          },
        ]
      }
      record.detail = next
      return { ...next }
    },
    async listFollowUps(state = 'all') {
      const wanted = state === 'all' ? ['pending', 'drafted'] : [state]
      return followUps
        .filter((t) => wanted.includes(t.state))
        .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))
        .map((t) => ({ ...t }))
    },
    async skipFollowUp(id) {
      const task = requirePending(id)
      return replaceFollowUp({
        ...task,
        state: 'skipped',
        cancel_reason: 'user_skipped',
        can_skip: false,
      })
    },
    async delayFollowUp(id, days) {
      const task = requirePending(id)
      const due_at = new Date(Date.parse(task.due_at) + days * 86_400_000).toISOString()
      return replaceFollowUp({ ...task, due_at })
    },
    async listSequences() {
      return sequences.map((s) => ({ ...s }))
    },
    async createSequence(input) {
      checkSequence(input.steps)
      const created: Sequence = {
        ...input,
        id: crypto.randomUUID(),
        is_default: input.make_default,
      }
      sequences = [...sequences, created]
      return replaceSequence(created)
    },
    async updateSequence(id, patch) {
      const current = sequences.find((s) => s.id === id)
      if (!current) throw new ApiError(404, 'Not found')
      checkSequence(patch.steps)
      const { make_default, ...rest } = patch
      return replaceSequence({
        ...current,
        ...rest,
        is_default: make_default || current.is_default,
      })
    },
    async previewTemplate(template, tone) {
      const message = validateTemplate(template)
      if (message) {
        throw new ApiError(422, 'Invalid template', [
          { field: 'template', code: 'invalid_template', message },
        ])
      }
      return { text: renderPreview(template, tone) }
    },
  }
}
