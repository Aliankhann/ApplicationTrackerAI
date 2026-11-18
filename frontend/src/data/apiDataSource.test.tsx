import { screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { renderRoute } from '../test/render'
import { apiDataSource } from './apiDataSource'

afterEach(() => vi.unstubAllGlobals())

const stub = (body: unknown, status = 200) =>
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json(body, { status })),
  )

test('AC8: apiDataSource rejects a malformed API response', async () => {
  stub({ items: [{ id: 'not-a-uuid' }], next_cursor: null })
  await expect(apiDataSource.listApplications({})).rejects.toThrow()
})

test('AC8: the page shows the error state for a malformed response', async () => {
  stub({ items: [{ company: 42 }], next_cursor: null })
  renderRoute('/app')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load applications.')
})

test('AC9: /app with a 401 shows the sign-in placeholder linking to /sign-in and /demo', async () => {
  stub({ detail: 'unauthenticated' }, 401)
  renderRoute('/app')
  expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Go to sign in' })).toHaveAttribute('href', '/sign-in')
  expect(screen.getByRole('link', { name: 'Try the demo' })).toHaveAttribute('href', '/demo')
})
