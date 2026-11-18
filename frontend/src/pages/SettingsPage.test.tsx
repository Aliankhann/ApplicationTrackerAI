import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError, type DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import { Route, Routes } from 'react-router'
import GoodbyePage from './GoodbyePage'
import SettingsPage from './SettingsPage'

const throwingFetch = vi.fn(() => {
  throw new Error('network is forbidden in demo mode')
})
beforeEach(() => vi.stubGlobal('fetch', throwingFetch))
afterEach(() => vi.unstubAllGlobals())

function renderSettings(overrides: Partial<DataSource> = {}) {
  const source: DataSource = {
    ...createDemoDataSource(),
    kind: 'api',
    ...overrides,
  }
  return renderWithSource(
    source,
    <Routes>
      <Route path="/demo" element={<SettingsPage />} />
      <Route path="/goodbye" element={<GoodbyePage />} />
    </Routes>,
  )
}

test('US-80: demo shows the data controls disabled with a note and never fetches', async () => {
  renderRoute('/demo/settings')
  expect(await screen.findByText('Not available in the demo.')).toBeVisible()
  expect(screen.getByRole('button', { name: 'Disconnect Gmail' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Delete my account and data' })).toBeDisabled()
  expect(screen.getByRole('link', { name: 'Follow-up settings' })).toHaveAttribute(
    'href',
    '/demo/settings/follow-ups',
  )
  expect(throwingFetch).not.toHaveBeenCalled()
})

test('US-80: the demo data source refuses both actions', async () => {
  const demo = createDemoDataSource()
  await expect(demo.disconnectGmail()).rejects.toBeInstanceOf(ApiError)
  await expect(demo.deleteAccount()).rejects.toThrow('Not available in the demo')
})

test('US-35: dialogs open with focus inside, close with Escape, and Cancel closes', async () => {
  const user = userEvent.setup()
  renderSettings()
  screen.getByRole('button', { name: 'Disconnect Gmail' }).focus()
  await user.click(screen.getByRole('button', { name: 'Disconnect Gmail' }))
  const dialog = screen.getByRole('dialog', { name: 'Disconnect Gmail?' })
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog).toContainElement(document.activeElement as HTMLElement)
  fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'Escape' })
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(screen.getByRole('button', { name: 'Disconnect Gmail' })).toHaveFocus()

  await user.click(screen.getByRole('button', { name: 'Delete my account and data' }))
  expect(screen.getByRole('dialog', { name: 'Delete your account and data?' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('US-35: disconnect confirms, calls the source once, and reports success', async () => {
  const disconnectGmail = vi.fn<DataSource['disconnectGmail']>(async () => ({
    revoked_at_google: true,
  }))
  const user = userEvent.setup()
  renderSettings({ disconnectGmail })
  await user.click(screen.getByRole('button', { name: 'Disconnect Gmail' }))
  await user.click(
    screen.getByRole('button', {
      name: 'Disconnect Gmail and delete synced data',
    }),
  )
  expect(await screen.findByRole('status')).toHaveTextContent('Gmail disconnected')
  expect(
    screen.queryByRole('link', {
      name: 'Remove access in your Google Account',
    }),
  ).toBeNull()
  expect(disconnectGmail).toHaveBeenCalledTimes(1)
  expect(screen.queryByRole('dialog')).toBeNull()
})

test('US-35: when Google revocation failed the user is told to remove access themselves', async () => {
  const user = userEvent.setup()
  renderSettings({
    disconnectGmail: async () => ({ revoked_at_google: false }),
  })
  await user.click(screen.getByRole('button', { name: 'Disconnect Gmail' }))
  await user.click(
    screen.getByRole('button', {
      name: 'Disconnect Gmail and delete synced data',
    }),
  )
  const link = await screen.findByRole('link', {
    name: 'Remove access in your Google Account',
  })
  expect(link).toHaveAttribute('href', 'https://myaccount.google.com/permissions')
})

test('US-35: a running sync (409) shows a retry message and keeps the dialog open', async () => {
  const user = userEvent.setup()
  renderSettings({
    disconnectGmail: async () => {
      throw new ApiError(409, 'Request failed (409)')
    },
  })
  await user.click(screen.getByRole('button', { name: 'Disconnect Gmail' }))
  await user.click(
    screen.getByRole('button', {
      name: 'Disconnect Gmail and delete synced data',
    }),
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('A sync is running')
  expect(screen.getByRole('dialog')).toBeVisible()
})

test('US-80: delete stays disabled until DELETE is typed exactly', async () => {
  const deleteAccount = vi.fn<DataSource['deleteAccount']>()
  const user = userEvent.setup()
  renderSettings({ deleteAccount })
  await user.click(screen.getByRole('button', { name: 'Delete my account and data' }))
  const confirm = screen.getByRole('button', {
    name: 'Permanently delete my account and data',
  })
  const input = screen.getByLabelText('Type DELETE to confirm')
  expect(input).toHaveFocus()
  expect(confirm).toBeDisabled()
  await user.type(input, 'delete')
  expect(confirm).toBeDisabled()
  await user.clear(input)
  await user.type(input, 'DELETE')
  expect(confirm).toBeEnabled()
  expect(deleteAccount).not.toHaveBeenCalled()
})

test('US-80: confirmed deletion routes to the goodbye page with the backup note', async () => {
  const deleteAccount = vi.fn<DataSource['deleteAccount']>(async () => ({
    deleted: true,
    revoked_at_google: true,
  }))
  const user = userEvent.setup()
  renderSettings({ deleteAccount })
  await user.click(screen.getByRole('button', { name: 'Delete my account and data' }))
  await user.type(screen.getByLabelText('Type DELETE to confirm'), 'DELETE')
  await user.click(
    screen.getByRole('button', {
      name: 'Permanently delete my account and data',
    }),
  )
  expect(
    await screen.findByRole('heading', {
      name: 'Your account and data were deleted',
    }),
  ).toBeVisible()
  expect(screen.getByText(/Backups expire within \d+ days/)).toBeVisible()
  expect(
    screen.queryByRole('link', {
      name: 'Remove access in your Google Account',
    }),
  ).toBeNull()
  expect(deleteAccount).toHaveBeenCalledTimes(1)
})

test('US-80: goodbye page tells the user to remove access when Google revocation failed', async () => {
  const user = userEvent.setup()
  renderSettings({
    deleteAccount: async () => ({ deleted: true, revoked_at_google: false }),
  })
  await user.click(screen.getByRole('button', { name: 'Delete my account and data' }))
  await user.type(screen.getByLabelText('Type DELETE to confirm'), 'DELETE')
  await user.click(
    screen.getByRole('button', {
      name: 'Permanently delete my account and data',
    }),
  )
  await waitFor(() =>
    expect(
      screen.getByRole('link', {
        name: 'Remove access in your Google Account',
      }),
    ).toBeVisible(),
  )
})
