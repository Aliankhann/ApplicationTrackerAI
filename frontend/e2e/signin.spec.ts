import { expect, test } from '@playwright/test'
import { API_BASE_URL } from './helpers.ts'

const VALID_CODE = 'ABCD-EFGH-IJKL-MNOP-QRST-UVWX-2345-6723'

test('sign-in: a rejected invite code shows an error', async ({ page }) => {
  await page.route(`${API_BASE_URL}/auth/invite`, (route) =>
    route.fulfill({ status: 400, json: {} }),
  )
  await page.goto('/sign-in')
  await page.getByRole('button', { name: 'Sign up' }).click()
  await page.getByRole('textbox', { name: 'Invite code' }).fill(VALID_CODE)
  await page.getByRole('button', { name: 'Check code' }).click()
  await expect(page.getByRole('alert')).toContainText('not valid')
})

test('sign-in: an accepted code leads to the Google step pointing at the API', async ({ page }) => {
  await page.route(`${API_BASE_URL}/auth/invite`, (route) => route.fulfill({ status: 204 }))
  await page.goto('/sign-in')
  await page.getByRole('button', { name: 'Sign up' }).click()
  await page.getByRole('textbox', { name: 'Invite code' }).fill(VALID_CODE)
  await page.getByRole('button', { name: 'Check code' }).click()
  await expect(page.getByRole('heading', { name: 'Your code is accepted' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    `${API_BASE_URL}/auth/google/start?mode=signup`,
  )
})

test('sign-in: the Sign in choice goes straight to Google without a code', async ({ page }) => {
  await page.goto('/sign-in')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('textbox', { name: 'Invite code' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Continue with Google' })).toHaveAttribute(
    'href',
    `${API_BASE_URL}/auth/google/start?mode=signin`,
  )
})

test('/app with a 401 shows the sign-in-required page', async ({ page }) => {
  await page.route(`${API_BASE_URL}/**`, (route) => route.fulfill({ status: 401, json: {} }))
  await page.goto('/app')
  await expect(page.getByText('You need to sign in to see your applications.')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Go to sign in' })).toBeVisible()
})

const APP_ID = '3f0c2c4e-5b1a-4c55-9a53-0a1b2c3d4e5f'
const NOW = new Date().toISOString()
const APPLICATION = {
  id: APP_ID,
  company: 'Mockco',
  role: 'Intern',
  status: 'applied',
  display_status: 'applied',
  applied_at: NOW,
  last_activity_at: NOW,
  status_locked: false,
  needs_review: false,
  followups_paused: false,
}

test('/app renders mocked data and PATCH sends the CSRF header from the cookie', async ({
  page,
  context,
}) => {
  await context.addCookies([
    {
      name: 'tracker_csrf',
      value: 'csrf-test-token',
      url: 'http://localhost:4173',
    },
  ])
  let patchHeaders: Record<string, string> | undefined
  await page.route(`${API_BASE_URL}/**`, async (route) => {
    const request = route.request()
    const cors = {
      'access-control-allow-origin': 'http://localhost:4173',
      'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'x-csrf-token, content-type',
      'access-control-allow-methods': 'GET, POST, PATCH, OPTIONS',
    }
    const { pathname } = new URL(request.url())
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: cors })
    const json = (body: unknown) => route.fulfill({ status: 200, headers: cors, json: body })
    if (pathname === '/gmail/status') return json({ connected: true, followups_enabled: false })
    if (pathname === '/sync')
      return json({ running: false, last_synced_at: null, last_error: null })
    if (pathname === '/applications') return json({ items: [APPLICATION], next_cursor: null })
    if (pathname === `/applications/${APP_ID}/events`) return json([])
    if (pathname === `/applications/${APP_ID}`) {
      if (request.method() === 'PATCH') {
        patchHeaders = request.headers()
        return json({
          ...APPLICATION,
          subject: null,
          snippet: null,
          status: 'offer',
          display_status: 'offer',
        })
      }
      return json({ ...APPLICATION, subject: null, snippet: null })
    }
    return route.fulfill({ status: 404, headers: cors, json: {} })
  })

  await page.goto('/app')
  await page.getByRole('link', { name: /Mockco/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Mockco' })).toBeVisible()
  await page.getByLabel('Change status').selectOption('offer')
  await expect.poll(() => patchHeaders?.['x-csrf-token']).toBe('csrf-test-token')
})
