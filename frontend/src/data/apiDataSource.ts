import { api } from '../api/client'
import { ApiError, type DataSource } from './dataSource'
import {
  ApplicationDetailSchema,
  ApplicationPageSchema,
  ConnectResultSchema,
  DeleteResultSchema,
  DisconnectResultSchema,
  FieldErrorsSchema,
  FollowUpSchema,
  FollowUpsSchema,
  GmailStatusSchema,
  MeSchema,
  PreviewSchema,
  SequenceSchema,
  SequencesSchema,
  SettingsSchema,
  StatusEventsSchema,
  SyncStartSchema,
  SyncStatusSchema,
  type ListParams,
} from './schemas'

interface Result {
  data?: unknown
  error?: unknown
  response: Response
}

function fieldErrorsOf(error: unknown) {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  const parsed = FieldErrorsSchema.safeParse(detail)
  return parsed.success ? parsed.data : []
}

// Validation failures (ZodError) and HTTP failures both throw; unvalidated data never escapes.
function unwrap({ data, error, response }: Result): unknown {
  if (error !== undefined || !response.ok) {
    throw new ApiError(response.status, `Request failed (${response.status})`, fieldErrorsOf(error))
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
  async listFollowUps(state) {
    return FollowUpsSchema.parse(
      unwrap(await api.GET('/follow-ups', { params: { query: { state } } })),
    )
  },
  async skipFollowUp(id) {
    const params = { path: { task_id: id } }
    return FollowUpSchema.parse(unwrap(await api.POST('/follow-ups/{task_id}/skip', { params })))
  },
  async delayFollowUp(id, days) {
    const params = { path: { task_id: id } }
    const result = await api.POST('/follow-ups/{task_id}/delay', {
      params,
      body: { days },
    })
    return FollowUpSchema.parse(unwrap(result))
  },
  async listSequences() {
    return SequencesSchema.parse(unwrap(await api.GET('/sequences')))
  },
  async createSequence(input) {
    return SequenceSchema.parse(unwrap(await api.POST('/sequences', { body: input })))
  },
  async updateSequence(id, patch) {
    const params = { path: { sequence_id: id } }
    return SequenceSchema.parse(
      unwrap(await api.PATCH('/sequences/{sequence_id}', { params, body: patch })),
    )
  },
  async previewTemplate(template, tone) {
    const body = { template, tone }
    return PreviewSchema.parse(unwrap(await api.POST('/sequences/preview', { body })))
  },
  async getSettings() {
    return SettingsSchema.parse(unwrap(await api.GET('/settings')))
  },
  async updateSettings(patch) {
    return SettingsSchema.parse(unwrap(await api.PATCH('/settings', { body: patch })))
  },
  async getMe() {
    return MeSchema.parse(unwrap(await api.GET('/me')))
  },
  async getGmailStatus() {
    return GmailStatusSchema.parse(unwrap(await api.GET('/gmail/status')))
  },
  async startGmailConnect(followups) {
    return ConnectResultSchema.parse(
      unwrap(await api.POST('/gmail/connect', { body: { followups } })),
    )
  },
  async startSync() {
    return SyncStartSchema.parse(unwrap(await api.POST('/sync')))
  },
  async getSyncStatus() {
    return SyncStatusSchema.parse(unwrap(await api.GET('/sync')))
  },
  async disconnectGmail() {
    return DisconnectResultSchema.parse(unwrap(await api.POST('/gmail/disconnect')))
  },
  async deleteAccount() {
    const body = { confirm: 'DELETE' as const }
    return DeleteResultSchema.parse(unwrap(await api.DELETE('/me', { body })))
  },
}
