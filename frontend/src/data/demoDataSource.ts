import { buildDemoRecords, type DemoRecord } from '../demo/data'
import { ApiError, type DataSource } from './dataSource'
import type { ApplicationDetail, ListParams } from './schemas'

const DEFAULT_LIMIT = 50

function sortKey(record: DemoRecord, sort: ListParams['sort']): number {
  const { detail } = record
  const value = sort === 'applied_at' ? detail.applied_at : detail.last_activity_at
  return value ? Date.parse(value) : 0
}

// In-memory only: never touches the network. Each instance starts from the seeded dataset.
export function createDemoDataSource(now: Date = new Date()): DataSource {
  const records = buildDemoRecords(now)

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
  }
}
