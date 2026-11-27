import { STATUSES } from '../data/schemas'

export const STATUS_LABELS: Record<string, string> = {
  applied: 'Applied',
  online_assessment: 'Online assessment',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  ghosted: 'Ghosted',
  needs_review: 'Needs review',
}

// Labels the pipeline can suggest for a card it could not decide (classifier label values).
const SUGGESTION_LABELS: Record<string, string> = {
  confirmation: 'Applied',
  online_assessment: 'Online assessment',
  interview: 'Interview',
  offer: 'Offer',
  rejection: 'Rejected',
}

export const suggestionLabel = (label: string | null): string | null =>
  label === null ? null : (SUGGESTION_LABELS[label] ?? null)

// "Needs review" comes first and the board only shows it while something waits there.
export const REVIEW_COLUMN = 'needs_review'
export const BOARD_COLUMNS = [REVIEW_COLUMN, ...STATUSES, 'ghosted'] as const

export const statusLabel = (status: string): string => STATUS_LABELS[status] ?? status

const DAY_MS = 86_400_000

export function relativeDate(iso: string, now: Date = new Date()): string {
  const days = Math.floor((now.getTime() - Date.parse(iso)) / DAY_MS)
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days} days ago`
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

export function shortDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString(undefined, { dateStyle: 'medium' }) : 'Not detected'
}

export function reasonText(reason: string): string {
  if (reason === 'created') return 'created'
  if (reason === 'manual') return 'changed by you'
  if (reason.startsWith('classifier:')) return 'detected from email'
  return 'updated'
}
