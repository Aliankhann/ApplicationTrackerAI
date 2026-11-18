import { z } from 'zod'
import type { components } from '../api/schema'

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
]

export const COMPANY_MAX = 80
export const ROLE_MAX = 120

export function validateText(value: string, max: number, label: string): string | null {
  const length = value.trim().length
  if (length < 1 || length > max) return `${label} must be 1 to ${max} characters.`
  return null
}
