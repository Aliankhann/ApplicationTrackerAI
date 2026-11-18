import { afterEach, expect, test, vi } from 'vitest'
import { ConnectResultSchema } from '../data/schemas'
import { navigateTo } from './navigate'

const GOOD = 'https://accounts.google.com/o/oauth2/v2/auth?x=1'
const BAD = [
  'https://evil.example/o/oauth2/v2/auth',
  'javascript:alert(1)',
  'http://accounts.google.com/o/oauth2/v2/auth',
  'https://accounts.google.com.evil.example/auth',
  'https://accounts.google.com@evil.example/auth',
  'https://accounts.google.com:8443/auth',
  'not a url',
]

afterEach(() => vi.unstubAllGlobals())

test('US-31: navigateTo goes to accounts.google.com over https', () => {
  const assign = vi.fn()
  vi.stubGlobal('location', { assign })
  navigateTo(GOOD)
  expect(assign).toHaveBeenCalledWith(GOOD)
})

test.each(BAD)('US-31: navigateTo refuses %s', (url) => {
  const assign = vi.fn()
  vi.stubGlobal('location', { assign })
  expect(() => navigateTo(url)).toThrow()
  expect(assign).not.toHaveBeenCalled()
})

test.each(BAD)('US-31: the response schema rejects %s', (url) => {
  expect(ConnectResultSchema.safeParse({ authorize_url: url }).success).toBe(false)
  expect(ConnectResultSchema.safeParse({ authorize_url: GOOD }).success).toBe(true)
})
