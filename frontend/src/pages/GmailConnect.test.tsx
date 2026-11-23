import { act, screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { DataSource } from '../data/dataSource'
import { ApiError } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import type { GmailStatus, SyncStatus } from '../data/schemas'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import DashboardPage from './DashboardPage'
import SettingsPage from './SettingsPage'
import { navigateTo } from './navigate'

vi.mock('./navigate', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./navigate')>()),
  navigateTo: vi.fn(),
}))

const throwingFetch = vi.fn(() => {
  throw new Error('network is forbidden in demo mode')
})
beforeEach(() => vi.stubGlobal('fetch', throwingFetch))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  vi.mocked(navigateTo).mockClear()
})

const IDLE: SyncStatus = {
  status: 'idle',
  last_synced_at: null,
  initial_sync_done: false,
  last_error: null,
}
const DISCONNECTED: GmailStatus = { connected: false, followups_enabled: false }
const CONNECTED: GmailStatus = { connected: true, followups_enabled: false }

function source(overrides: Partial<DataSource>): DataSource {
  return { ...createDemoDataSource(), kind: 'api', ...overrides }
}

function renderDashboard(overrides: Partial<DataSource>, route = '/demo') {
  return renderWithSource(
    source(overrides),
    <Routes>
      <Route path="/demo" element={<DashboardPage />} />
    </Routes>,
    route,
  )
}

test('US-31: not connected shows the Connect Gmail card, which explains and links to privacy', async () => {
  const user = userEvent.setup()
  const startGmailConnect = vi.fn(async () => ({
    authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1',
  }))
  renderDashboard({ getGmailStatus: async () => DISCONNECTED, startGmailConnect })
  expect(await screen.findByRole('heading', { name: 'Connect Gmail' })).toBeVisible()
  expect(screen.getByText(/We never store full emails/)).toBeVisible()
  expect(screen.getByRole('link', { name: 'What we read and store' })).toHaveAttribute(
    'href',
    '/privacy',
  )
  await user.click(screen.getByRole('button', { name: 'Connect Gmail' }))
  expect(startGmailConnect).toHaveBeenCalledWith(false)
  await waitFor(() =>
    expect(navigateTo).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?x=1'),
  )
})

test('US-31: a failed connect start says so and does not navigate', async () => {
  const user = userEvent.setup()
  renderDashboard({
    getGmailStatus: async () => DISCONNECTED,
    startGmailConnect: async () => {
      throw new ApiError(503, 'unavailable')
    },
  })
  await user.click(await screen.findByRole('button', { name: 'Connect Gmail' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not start the connection')
  expect(navigateTo).not.toHaveBeenCalled()
})

test('US-31: the demo shows Connect Gmail disabled with the demo note and never fetches', async () => {
  renderRoute('/demo')
  expect(await screen.findByRole('button', { name: 'Connect Gmail' })).toBeDisabled()
  expect(screen.getByText('Gmail is not available in the demo.')).toBeVisible()
  expect(throwingFetch).not.toHaveBeenCalled()
})

test('US-34: connected shows Sync now with the last synced time, and starts a sync once', async () => {
  const user = userEvent.setup()
  const startSync = vi.fn(async () => ({ status: 'completed' as const }))
  renderDashboard({
    getGmailStatus: async () => CONNECTED,
    getSyncStatus: async () => ({
      ...IDLE,
      last_synced_at: '2026-01-01T12:00:00Z',
      initial_sync_done: true,
    }),
    startSync,
  })
  expect(await screen.findByText(/^Last synced /)).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Sync now' }))
  expect(startSync).toHaveBeenCalledTimes(1)
})

test('US-34: while running it polls every 3 seconds, disables the button, then shows the result', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup()
  let polls = 0
  const getSyncStatus = vi.fn(async (): Promise<SyncStatus> => {
    polls += 1
    if (polls <= 3) return { ...IDLE, status: 'running' }
    return { ...IDLE, last_synced_at: '2026-01-01T12:00:00Z', initial_sync_done: true }
  })
  renderDashboard({
    getGmailStatus: async () => CONNECTED,
    getSyncStatus,
    startSync: async () => ({ status: 'completed' }),
  })
  await screen.findByRole('button', { name: 'Sync now' })
  await user.click(screen.getByRole('button', { name: 'Sync now' }))
  expect(await screen.findByText('Syncing your email…')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Sync now' })).toBeDisabled()
  const before = getSyncStatus.mock.calls.length
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(getSyncStatus.mock.calls.length).toBeGreaterThan(before)
  await act(() => vi.advanceTimersByTimeAsync(9000))
  expect(await screen.findByText(/^Last synced /)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled()
})

test('US-34: a failed sync is explained in plain words, not as a code', async () => {
  renderDashboard({
    getGmailStatus: async () => CONNECTED,
    getSyncStatus: async () => ({ ...IDLE, status: 'error', last_error: 'rate_limited' }),
  })
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent('Gmail asked us to slow down')
  expect(alert).not.toHaveTextContent('rate_limited')
})

test('US-34: a rate-limited start is reported', async () => {
  const user = userEvent.setup()
  renderDashboard({
    getGmailStatus: async () => CONNECTED,
    getSyncStatus: async () => IDLE,
    startSync: async () => {
      throw new ApiError(429, 'rate_limited')
    },
  })
  await user.click(await screen.findByRole('button', { name: 'Sync now' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not run a sync')
})

test('US-31: returning with ?connected=1 shows a success note and starts the first sync once', async () => {
  const startSync = vi.fn(async () => ({ status: 'completed' as const }))
  renderDashboard(
    { getGmailStatus: async () => CONNECTED, getSyncStatus: async () => IDLE, startSync },
    '/demo?connected=1',
  )
  expect(await screen.findByText(/Gmail is connected/)).toBeVisible()
  await waitFor(() => expect(startSync).toHaveBeenCalledTimes(1))
  await new Promise((resolve) => setTimeout(resolve, 20))
  expect(startSync).toHaveBeenCalledTimes(1)
})

function renderSettings(overrides: Partial<DataSource>, route = '/demo') {
  return renderWithSource(
    source(overrides),
    <Routes>
      <Route path="/demo" element={<SettingsPage />} />
    </Routes>,
    route,
  )
}

test('US-31: settings shows the connection and turns on follow-up drafts by requesting compose', async () => {
  const user = userEvent.setup()
  const startGmailConnect = vi.fn(async () => ({ authorize_url: 'https://accounts.google.com/x' }))
  renderSettings({ getGmailStatus: async () => CONNECTED, startGmailConnect })
  expect(await screen.findByText(/Gmail is connected\./)).toBeVisible()
  expect(screen.getByText(/Follow-up drafts are off\./)).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Turn on follow-up drafts' }))
  expect(startGmailConnect).toHaveBeenCalledWith(true)
  await waitFor(() => expect(navigateTo).toHaveBeenCalledWith('https://accounts.google.com/x'))
})

test('US-31: with follow-ups already on there is no button to turn them on', async () => {
  renderSettings({ getGmailStatus: async () => ({ connected: true, followups_enabled: true }) })
  expect(await screen.findByText(/Follow-up drafts are on\./)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Turn on follow-up drafts' })).toBeNull()
})

test.each([
  ['account_mismatch', /not the one you signed in with/],
  ['no_refresh_token', /did not give us lasting access/],
  ['scope_denied', /read access was not approved/],
  ['followups_denied', /still connected for reading only/],
  ['flow_invalid', /expired or did not match/],
  ['access_denied', /You cancelled/],
  ['something_new', /did not work/],
])('US-31: gmail_error=%s is shown as a plain message', async (code, message) => {
  renderSettings({ getGmailStatus: async () => DISCONNECTED }, `/demo?gmail_error=${code}`)
  const alert = await screen.findByRole('alert')
  expect(alert).toHaveTextContent(message)
  expect(alert).not.toHaveTextContent(code)
})

test('US-31: the demo settings keep follow-up drafts unavailable', async () => {
  renderRoute('/demo/settings')
  expect(await screen.findByText('Gmail is not connected.')).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Turn on follow-up drafts' })).toBeNull()
  expect(throwingFetch).not.toHaveBeenCalled()
})
