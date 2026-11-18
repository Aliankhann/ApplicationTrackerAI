import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError, type DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import FollowUpsPage from './FollowUpsPage'

const throwingFetch = vi.fn(() => {
  throw new Error('network is forbidden in demo mode')
})
beforeEach(() => vi.stubGlobal('fetch', throwingFetch))
afterEach(() => {
  throwingFetch.mockClear()
  vi.unstubAllGlobals()
})

const section = (name: string) => screen.getByRole('heading', { name }).closest('section')!

test('US-66: demo page groups drafts and scheduled follow-ups and never fetches', async () => {
  renderRoute('/demo/follow-ups')
  expect(await screen.findByRole('heading', { name: 'Drafts waiting for you' })).toBeVisible()
  expect(
    within(section('Drafts waiting for you')).getByText('Open Gmail to review and send.'),
  ).toBeVisible()
  expect(within(section('Scheduled')).getAllByRole('button', { name: 'Skip' })).toHaveLength(2)
  expect(throwingFetch).not.toHaveBeenCalled()
})

test('US-66: nav links to applications, follow-ups, and settings', async () => {
  renderRoute('/demo/follow-ups')
  const nav = await screen.findByRole('navigation', { name: 'Main' })
  expect(within(nav).getByRole('link', { name: 'Settings' })).toHaveAttribute(
    'href',
    '/demo/settings',
  )
  expect(within(nav).getByRole('link', { name: 'Applications' })).toHaveAttribute('href', '/demo')
})

test('US-66: skip removes the row optimistically', async () => {
  const user = userEvent.setup()
  renderRoute('/demo/follow-ups')
  const scheduled = await screen.findByRole('heading', { name: 'Scheduled' })
  const before = within(scheduled.closest('section')!).getAllByRole('listitem').length
  await user.click(
    within(scheduled.closest('section')!).getAllByRole('button', { name: 'Skip' })[0]!,
  )
  await waitFor(() =>
    expect(within(section('Scheduled')).getAllByRole('listitem')).toHaveLength(before - 1),
  )
})

test('US-66: delay 3 days moves the due date later', async () => {
  const demo = createDemoDataSource()
  const delay = vi.fn<DataSource['delayFollowUp']>(demo.delayFollowUp)
  const user = userEvent.setup()
  renderWithSource({ ...demo, delayFollowUp: delay }, <FollowUpsPage />)
  await user.click((await screen.findAllByRole('button', { name: 'Delay 3 days' }))[0]!)
  await waitFor(() => expect(delay).toHaveBeenCalledWith(expect.any(String), 3))
})

test('US-66: a failed skip rolls back the row and shows an alert', async () => {
  const demo = createDemoDataSource()
  const skip = vi.fn<DataSource['skipFollowUp']>(async () => {
    throw new ApiError(409, 'Not pending')
  })
  const user = userEvent.setup()
  renderWithSource({ ...demo, skipFollowUp: skip }, <FollowUpsPage />)
  const before = (await screen.findAllByRole('button', { name: 'Skip' })).length
  await user.click(screen.getAllByRole('button', { name: 'Skip' })[0]!)
  expect(await screen.findByRole('alert')).toHaveTextContent('The change was reverted.')
  expect(screen.getAllByRole('button', { name: 'Skip' })).toHaveLength(before)
})

test('US-66: empty state and error state', async () => {
  const demo = createDemoDataSource()
  const { unmount } = renderWithSource(
    { ...demo, listFollowUps: async () => [] },
    <FollowUpsPage />,
  )
  expect(await screen.findByText(/No upcoming follow-ups/)).toBeVisible()
  unmount()
  renderWithSource(
    {
      ...demo,
      listFollowUps: async () => {
        throw new Error('boom')
      },
    },
    <FollowUpsPage />,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load follow-ups.')
})
