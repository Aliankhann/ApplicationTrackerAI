import { API_BASE_URL, api } from '../api/client'

// Invite codes are 32 base32 characters (A-Z, 2-7) shown in groups of four.
const CODE_LENGTH = 32
export const CODE_HINT = 'XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX'
export const GOOGLE_START_URL = `${API_BASE_URL}/auth/google/start`

export function normalizeCode(raw: string): string {
  return raw.replace(/[\s-]+/g, '').toUpperCase()
}

export function formatCode(raw: string): string {
  return normalizeCode(raw).match(/.{1,4}/g)?.join('-') ?? ''
}

export type CodeProblem = 'empty' | 'length' | 'characters'

export function validateCode(raw: string): CodeProblem | null {
  const code = normalizeCode(raw)
  if (code.length === 0) return 'empty'
  if (!/^[A-Z2-7]+$/.test(code)) return 'characters'
  if (code.length !== CODE_LENGTH) return 'length'
  return null
}

export const CODE_PROBLEM_MESSAGES: Record<CodeProblem, string> = {
  empty: 'Enter your invite code.',
  length: `That code looks incomplete. It has 8 groups of 4 characters, like ${CODE_HINT}.`,
  characters: 'Invite codes only use the letters A to Z and the digits 2 to 7.',
}

const GENERIC = 'Sign-in did not work. Please try again.'

export const ERROR_MESSAGES: Record<string, string> = {
  not_invited:
    'This Google account is not invited yet. Enter a valid invite code first, or ask for a new one.',
  invalid_invite: 'That invite code is not valid. It may be mistyped, already used, or expired.',
  sign_in_failed: GENERIC,
  sign_in_cancelled: 'Sign-in was cancelled. You can try again whenever you are ready.',
  account_disabled: 'This account has been disabled. Contact the person who invited you.',
  rate_limited: 'Too many attempts. Please wait a while and try again.',
  sign_in_unavailable: 'Sign-in is not available right now. Please try again later.',
}

export function messageForError(code: string | null): string | null {
  if (!code) return null
  return ERROR_MESSAGES[code] ?? GENERIC
}

// A stable error code for each way the invite check can fail.
export async function submitInvite(raw: string): Promise<string | null> {
  try {
    const { response } = await api.POST('/auth/invite', { body: { code: formatCode(raw) } })
    if (response.ok) return null
    if (response.status === 400) return 'invalid_invite'
    if (response.status === 429) return 'rate_limited'
    if (response.status === 503) return 'sign_in_unavailable'
    return 'sign_in_failed'
  } catch {
    return 'sign_in_failed'
  }
}
