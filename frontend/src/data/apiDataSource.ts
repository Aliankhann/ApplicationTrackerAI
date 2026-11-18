import { api } from '../api/client'
import { ApiError, type DataSource } from './dataSource'
import {
  ApplicationDetailSchema,
  ApplicationPageSchema,
  StatusEventsSchema,
  type ListParams,
} from './schemas'

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

// Validation failures (ZodError) and HTTP failures both throw; unvalidated data never escapes.
function unwrap({ data, error, response }: Result): unknown {
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, `Request failed (${response.status})`)
  }
  return data
}

export const apiDataSource: DataSource = {
  kind: 'api',
  async listApplications(params: ListParams) {
    const { status, sort, order, limit, cursor } = params
    const query = { status, sort, order, limit, cursor }
    return ApplicationPageSchema.parse(
      unwrap(await api.GET('/applications', { params: { query } })),
    )
  },
  async getApplication(id) {
    const path = { application_id: id }
    const result = await api.GET('/applications/{application_id}', {
      params: { path },
    })
    return ApplicationDetailSchema.parse(unwrap(result))
  },
  async listEvents(id) {
    const path = { application_id: id }
    const result = await api.GET('/applications/{application_id}/events', {
      params: { path },
    })
    return StatusEventsSchema.parse(unwrap(result))
  },
  async updateApplication(id, patch) {
    const path = { application_id: id }
    const result = await api.PATCH('/applications/{application_id}', {
      params: { path },
      body: patch,
    })
    return ApplicationDetailSchema.parse(unwrap(result))
  },
}
