// Plain-words messages for the stable codes the backend sends.
const CONNECT_ERRORS: Record<string, string> = {
  account_mismatch:
    'That Google account is not the one you signed in with. Nothing was connected. Pick the same account and try again.',
  no_refresh_token:
    'Google did not give us lasting access, so nothing was connected. Please try again and approve every step.',
  scope_denied:
    'Gmail read access was not approved, so nothing was connected. We need it to find your application emails.',
  followups_denied:
    'Follow-up drafts were not approved. Gmail is still connected for reading only.',
  flow_invalid:
    'That connection attempt expired or did not match this browser. Please start again.',
  session_required: 'Please sign in and try again.',
  invite_expired:
    'Your invite is no longer valid, so Gmail was not connected. Ask for a new invite code and sign up again.',
  access_denied: 'You cancelled the connection. Nothing was changed.',
}

export function connectErrorMessage(code: string): string {
  return CONNECT_ERRORS[code] ?? 'Connecting to Gmail did not work. Please try again.'
}

export const RATE_LIMITED_TEXT = "Gmail asked us to slow down. We'll keep going on the next sync."

const SYNC_ERRORS: Record<string, string> = {
  auth_revoked: 'Google access was removed. Connect Gmail again to resume syncing.',
  rate_limited: RATE_LIMITED_TEXT,
  gmail_error: 'Gmail returned an error. We will try again at the next hourly sync.',
}

export function syncErrorMessage(code: string): string {
  return SYNC_ERRORS[code] ?? 'Something went wrong while syncing. We will try again soon.'
}
