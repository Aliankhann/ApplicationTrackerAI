import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { api } from './client'

let seen: Request[] = []

beforeEach(() => {
  seen = []
  document.cookie = 'tracker_csrf=abc123'
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      seen.push(request)
      return new Response(null, { status: 204 })
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'tracker_csrf=; Max-Age=0'
})

test('sends X-CSRF-Token from the cookie on POST, not on GET', async () => {
  await api.POST('/auth/logout')
  await api.GET('/me')
  expect(seen[0].headers.get('X-CSRF-Token')).toBe('abc123')
  expect(seen[1].headers.get('X-CSRF-Token')).toBeNull()
})

test('reads the __Host- prefixed CSRF cookie when present', async () => {
  // jsdom on http refuses to store __Host- cookies, so stub the cookie string.
  vi.spyOn(document, 'cookie', 'get').mockReturnValue('a=b; __Host-tracker_csrf=hosted')
  await api.DELETE('/auth/logout' as never)
  expect(seen[0].headers.get('X-CSRF-Token')).toBe('hosted')
  vi.restoreAllMocks()
})

test('does not send a CSRF header when no CSRF cookie exists (public sign-in routes)', async () => {
  document.cookie = 'tracker_csrf=; Max-Age=0'
  await api.POST('/auth/invite', { body: { code: 'X' } })
  expect(seen[0].headers.get('X-CSRF-Token')).toBeNull()
})
