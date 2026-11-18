import { z } from 'zod'
import type { components } from '../api/schema'
import { isGoogleAuthorizeUrl } from '../pages/navigate'

type Schemas = components['schemas']

export const STATUSES = ['applied', 'online_assessment', 'interview', 'offer', 'rejected'] as const
export const StatusSchema = z.enum(STATUSES)
export type Status = z.infer<typeof StatusSchema>

export const FILTER_STATUSES = [...STATUSES, 'ghosted'] as const
export type FilterStatus = (typeof FILTER_STATUSES)[number]

const timestamp = z.iso.datetime({ offset: true })

export const ApplicationSchema = z.object({
  id: z.uuid(),
  company: z.string().nullable(),
  role: z.string().nullable(),
  status: StatusSchema,
  display_status: z.string(),
  applied_at: timestamp.nullable(),
  last_activity_at: timestamp,
  status_locked: z.boolean(),
  needs_review: z.boolean(),
  followups_paused: z.boolean(),
})
export type Application = z.infer<typeof ApplicationSchema>

export const ApplicationDetailSchema = ApplicationSchema.extend({
  subject: z.string().nullable(),
  snippet: z.string().nullable(),
})
export type ApplicationDetail = z.infer<typeof ApplicationDetailSchema>

export const StatusEventSchema = z.object({
  from_status: StatusSchema.nullable(),
  to_status: StatusSchema,
  reason: z.string(),
  at: timestamp,
})
export type StatusEvent = z.infer<typeof StatusEventSchema>
export const StatusEventsSchema = z.array(StatusEventSchema)

export const ApplicationPageSchema = z.object({
  items: z.array(ApplicationSchema),
  next_cursor: z.string().nullable(),
})
export type ApplicationPage = z.infer<typeof ApplicationPageSchema>

export interface ApplicationPatch {
  status?: Status
  company?: string
  role?: string
  followups_paused?: boolean
}

export interface ListParams {
  status?: FilterStatus
  sort?: 'last_activity' | 'applied_at'
  order?: 'desc' | 'asc'
  limit?: number
  cursor?: string
}

export const FOLLOW_UP_STATES = ['pending', 'drafted', 'all'] as const
export type FollowUpFilter = (typeof FOLLOW_UP_STATES)[number]

export const FollowUpSchema = z.object({
  id: z.uuid(),
  application_id: z.uuid(),
  company: z.string().nullable(),
  role: z.string().nullable(),
  step_index: z.number().int(),
  due_at: timestamp,
  state: z.string(),
  cancel_reason: z.string().nullable(),
  can_skip: z.boolean(),
})
export type FollowUp = z.infer<typeof FollowUpSchema>
export const FollowUpsSchema = z.array(FollowUpSchema)

export const TONES = ['short', 'warm', 'formal'] as const
export type Tone = (typeof TONES)[number]

export const StepSchema = z.object({
  delay_days: z.number().int(),
  template: z.string(),
  max_attempts: z.number().int(),
})
export type Step = z.infer<typeof StepSchema>

export const SequenceSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  steps: z.array(StepSchema),
  tone: z.enum(TONES),
  is_default: z.boolean(),
})
export type Sequence = z.infer<typeof SequenceSchema>
export const SequencesSchema = z.array(SequenceSchema)

export interface SequenceInput {
  name: string
  steps: Step[]
  tone: Tone
  make_default: boolean
}
export type SequencePatch = Partial<SequenceInput>

export const PreviewSchema = z.object({ text: z.string() })
export type Preview = z.infer<typeof PreviewSchema>

export const FieldErrorsSchema = z.array(
  z.object({ field: z.string(), code: z.string(), message: z.string() }),
)
export type FieldError = z.infer<typeof FieldErrorsSchema>[number]

// Drift check: the Zod-inferred types must stay assignable to the generated API types.
type Assert<T extends true> = T
type Fits<A, B> = [A] extends [B] ? true : false
export type SchemaDriftChecks = [
  Assert<Fits<Application, Schemas['ApplicationOut']>>,
  Assert<Fits<ApplicationDetail, Schemas['ApplicationDetail']>>,
  Assert<Fits<StatusEvent, Schemas['EventOut']>>,
  Assert<Fits<ApplicationPage, Schemas['ApplicationPage']>>,
  Assert<Fits<ApplicationPatch, Schemas['ApplicationPatch']>>,
  Assert<Fits<Schemas['ApplicationDetail'], ApplicationDetail>>,
  Assert<Fits<FollowUp, Schemas['FollowUpOut']>>,
  Assert<Fits<Schemas['FollowUpOut'], FollowUp>>,
  Assert<Fits<Sequence, Schemas['SequenceOut']>>,
  Assert<Fits<SequenceInput, Schemas['SequenceCreate']>>,
  Assert<Fits<SequencePatch, Schemas['SequencePatch']>>,
  Assert<Fits<Preview, Schemas['PreviewOut']>>,
  Assert<Fits<Settings, Schemas['SettingsOut']>>,
  Assert<Fits<Schemas['SettingsOut'], Settings>>,
  Assert<Fits<GmailStatus, Schemas['GmailStatusOut']>>,
  Assert<Fits<Schemas['GmailStatusOut'], GmailStatus>>,
  Assert<Fits<ConnectResult, Schemas['GmailConnectOut']>>,
  Assert<Fits<SyncStart, Schemas['SyncStartOut']>>,
  Assert<Fits<SyncStatus, Schemas['SyncStatusOut']>>,
  Assert<Fits<Schemas['SyncStatusOut'], SyncStatus>>,
]

export const COMPANY_MAX = 80
export const ROLE_MAX = 120

export function validateText(value: string, max: number, label: string): string | null {
  const length = value.trim().length
  if (length < 1 || length > max) return `${label} must be 1 to ${max} characters.`
  return null
}

export const DisconnectResultSchema = z.object({
  revoked_at_google: z.boolean().nullable(),
})
export type DisconnectResult = z.infer<typeof DisconnectResultSchema>

export const SettingsSchema = z.object({ digest_enabled: z.boolean() })
export type Settings = z.infer<typeof SettingsSchema>

export const DeleteResultSchema = z.object({
  deleted: z.literal(true),
  revoked_at_google: z.boolean().nullable(),
})
export type DeleteResult = z.infer<typeof DeleteResultSchema>

export const GmailStatusSchema = z.object({
  connected: z.boolean(),
  followups_enabled: z.boolean(),
})
export type GmailStatus = z.infer<typeof GmailStatusSchema>

export const ConnectResultSchema = z.object({
  authorize_url: z
    .url({ protocol: /^https$/, hostname: /^accounts\.google\.com$/ })
    .refine(isGoogleAuthorizeUrl),
})
export type ConnectResult = z.infer<typeof ConnectResultSchema>

export const SyncStartSchema = z.object({
  status: z.enum(['started', 'already_running']),
})
export type SyncStart = z.infer<typeof SyncStartSchema>

export const SyncStatusSchema = z.object({
  status: z.enum(['idle', 'running', 'error', 'revoked']),
  last_synced_at: timestamp.nullable(),
  initial_sync_done: z.boolean(),
  last_error: z.string().nullable(),
})
export type SyncStatus = z.infer<typeof SyncStatusSchema>
