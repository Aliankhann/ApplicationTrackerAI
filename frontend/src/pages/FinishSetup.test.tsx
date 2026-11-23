import { fireEvent, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { renderRoute } from '../test/render'

afterEach(() => vi.unstubAllGlobals())

const ME = {
  id: '3f0c2c4e-5b1a-4c55-9a53-0a1b2c3d4e5f',
  email: 'new@example.test',
  timezone: null,
  setup_completed: false,
  invite_held_until: '2026-12-01T10:00:00Z',
  initial_sync_days: 45,
}

function stubApi(me: object, connectUrl = 'https://accounts.google.com/o/oauth2/v2/auth?x=1') {
  const fn = vi.fn(async (request: Request) => {
    const { pathname } = new URL(request.url)
    if (pathname === '/me') return Response.json(me)
    if (pathname === '/gmail/connect') return Response.json({ authorize_url: connectUrl })
    return Response.json({}, { status: 404 })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

test('AC: a pending user sees the finish-setup screen with the hold time instead of the app', async () => {
  stubApi(ME)
  renderRoute('/app')
  expect(await screen.findByRole('heading', { name: /Finish setup/ })).toBeVisible()
  expect(screen.getByRole('status')).toHaveTextContent('Your invite is held until')
  expect(screen.getByRole('link', { name: 'What we read and store' })).toHaveAttribute(
    'href',
    '/privacy',
  )
  expect(screen.queryByRole('navigation', { name: 'Main' })).toBeNull()
})

test('AC: the finish-setup Connect Gmail button starts the connection', async () => {
  const fetchMock = stubApi(ME)
  renderRoute('/app')
  fireEvent.click(await screen.findByRole('button', { name: 'Connect Gmail' }))
  await vi.waitFor(() =>
    expect(fetchMock.mock.calls.some(([r]) => new URL(r.url).pathname === '/gmail/connect')).toBe(
      true,
    ),
  )
})

test('AC: an invite_expired error is explained on the finish-setup screen', async () => {
  stubApi(ME)
  renderRoute('/app/settings?gmail_error=invite_expired')
  expect(await screen.findByRole('alert')).toHaveTextContent('Ask for a new invite code')
})

test('AC: the sync window in the copy comes from the API, not a hard-coded number', async () => {
  stubApi(ME)
  renderRoute('/app')
  expect(await screen.findByText(/from the last 45 days/)).toBeVisible()
})

test('AC: a user who finished setup sees the normal app navigation', async () => {
  stubApi({ ...ME, setup_completed: true, invite_held_until: null })
  renderRoute('/app')
  expect(await screen.findByRole('navigation', { name: 'Main' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: /Finish setup/ })).toBeNull()
})

test('AC: the demo never shows the finish-setup screen', async () => {
  stubApi(ME)
  renderRoute('/demo')
  expect(await screen.findByRole('navigation', { name: 'Main' })).toBeVisible()
  expect(screen.queryByRole('heading', { name: /Finish setup/ })).toBeNull()
})
