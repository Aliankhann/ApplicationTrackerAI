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

test('prefers the build-time CSRF cookie name (staging) over the default ones', async () => {
  vi.stubEnv('VITE_CSRF_COOKIE_NAME', 'tracker_csrf_staging')
  vi.resetModules()
  const fresh = await import('./client')
  expect(fresh.CSRF_COOKIES).toEqual([
    'tracker_csrf_staging',
    '__Host-tracker_csrf',
    'tracker_csrf',
  ])
  vi.spyOn(document, 'cookie', 'get').mockReturnValue(
    'tracker_csrf=prod-token; tracker_csrf_staging=staging-token',
  )
  await fresh.api.POST('/auth/logout')
  expect(seen[0].headers.get('X-CSRF-Token')).toBe('staging-token')
  vi.restoreAllMocks()
  vi.unstubAllEnvs()
})

test('without the build variable only the default CSRF cookie names are tried', async () => {
  vi.unstubAllEnvs()
  vi.resetModules()
  const fresh = await import('./client')
  expect(fresh.CSRF_COOKIES).toEqual(['__Host-tracker_csrf', 'tracker_csrf'])
})
