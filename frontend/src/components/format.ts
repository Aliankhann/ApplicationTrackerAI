import { FILTER_STATUSES } from '../data/schemas'

export const STATUS_LABELS: Record<string, string> = {
  applied: 'Applied',
  online_assessment: 'Online assessment',
  interview: 'Interview',
  offer: 'Offer',
  rejected: 'Rejected',
  ghosted: 'Ghosted',
}

export const BOARD_COLUMNS = FILTER_STATUSES

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
