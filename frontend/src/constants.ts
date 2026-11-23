// TODO: set once the database host and its backup schedule are chosen (US-05).
export const BACKUP_RETENTION_DAYS: number | null = null

export const GOOGLE_PERMISSIONS_URL = 'https://myaccount.google.com/permissions'

// TODO: replace with a real contact address before launch (US-81, US-103). Not a working mailbox.
export const CONTACT_MAILTO = 'mailto:contact-todo@example.invalid'

// Shown where no session exists (the public privacy page) and when the API does not say; the real
// value is the backend's INITIAL_SYNC_DAYS, sent as `initial_sync_days` on GET /me.
export const DEFAULT_INITIAL_SYNC_DAYS = 30

export const PRIVACY_LAST_UPDATED = '2026-11-18'
