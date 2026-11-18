import { screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import type { DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import ApplicationDetailPage from './ApplicationDetailPage'
import DashboardPage from './DashboardPage'

const throwingFetch = vi.fn(() => {
  throw new Error('network is forbidden in demo mode')
})

beforeEach(() => {
  localStorage.clear()
  throwingFetch.mockClear()
  vi.stubGlobal('fetch', throwingFetch)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

async function countByStatus() {
  const { items } = await createDemoDataSource().listApplications({
    limit: 100,
  })
  return (status: string) => items.filter((a) => a.display_status === status).length
}

test('AC1: board renders every status column with counts; ghosted has its own column', async () => {
  const count = await countByStatus()
  renderRoute('/demo')
  const columns: [string, string][] = [
    ['Applied', 'applied'],
    ['Online assessment', 'online_assessment'],
    ['Interview', 'interview'],
    ['Offer', 'offer'],
    ['Rejected', 'rejected'],
    ['Ghosted', 'ghosted'],
  ]
  for (const [label, status] of columns) {
    const heading = await screen.findByRole('heading', {
      name: `${label} (${count(status)})`,
    })
    expect(count(status)).toBeGreaterThan(0)
    expect(within(heading.closest('section')!).getAllByRole('link')).toHaveLength(count(status))
  }
  const ghosted = screen.getByRole('heading', { name: /^Ghosted/ }).closest('section')!
  expect(within(ghosted).getByText('Harbor & Vale')).toBeVisible()
  expect(screen.getByText('Unknown company')).toBeVisible()
  expect(screen.getAllByText('Role not detected').length).toBeGreaterThan(0)
  expect(screen.getAllByText('Needs review').length).toBeGreaterThan(0)
  expect(screen.getAllByText('Follow-ups paused').length).toBeGreaterThan(0)
})

async function openTable() {
  const user = userEvent.setup()
  renderRoute('/demo')
  await user.click(await screen.findByRole('radio', { name: 'Table view' }))
  return user
}

const firstCompany = () =>
  within(screen.getAllByRole('row')[1]!).getAllByRole('cell')[0]!.textContent

test('AC2: table view renders, sorts by last activity and applied, filters by status', async () => {
  const user = await openTable()
  expect(await screen.findByRole('table')).toBeVisible()
  expect(screen.getAllByRole('row')).toHaveLength(19)
  expect(firstCompany()).toBe('Unknown company')

  await user.selectOptions(screen.getByLabelText('Sort by'), 'last_activity:asc')
  await waitFor(() => expect(firstCompany()).toBe('Copperleaf Robotics'))

  await user.selectOptions(screen.getByLabelText('Sort by'), 'applied_at:desc')
  await waitFor(() => expect(firstCompany()).toBe('Northwind Labs'))

  await user.selectOptions(screen.getByLabelText('Filter by status'), 'ghosted')
  await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(4))
})

test('AC2: toggle choice persists and is restored', async () => {
  const user = await openTable()
  await screen.findByRole('table')
  expect(localStorage.getItem('tracker:view')).toBe('table')
  await user.click(screen.getByRole('radio', { name: 'Board view' }))
  expect(localStorage.getItem('tracker:view')).toBe('board')
  await user.click(screen.getByRole('radio', { name: 'Table view' }))
})

test('AC2: remembered choice is restored, and localStorage throwing is tolerated', async () => {
  localStorage.setItem('tracker:view', 'table')
  const { unmount } = renderRoute('/demo')
  expect(await screen.findByRole('table')).toBeVisible()
  unmount()

  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  const user = userEvent.setup()
  renderRoute('/demo')
  await user.click(await screen.findByRole('radio', { name: 'Table view' }))
  expect(await screen.findByRole('table')).toBeVisible()
})

const fakeSource = (list: DataSource['listApplications']): DataSource => ({
  kind: 'demo',
  listApplications: list,
  getApplication: vi.fn(),
  listEvents: vi.fn(),
  updateApplication: vi.fn(),
})

test('AC3: loading state has accessible text', () => {
  renderWithSource(
    fakeSource(() => new Promise(() => {})),
    <DashboardPage />,
  )
  expect(screen.getByRole('status')).toHaveTextContent('Loading applications')
})

test('AC3: empty state has accessible text and a demo link', async () => {
  renderWithSource(
    fakeSource(async () => ({ items: [], next_cursor: null })),
    <DashboardPage />,
  )
  expect(await screen.findByRole('heading', { name: 'No applications yet' })).toBeVisible()
  expect(screen.getByRole('link', { name: /demo/i })).toHaveAttribute('href', '/demo')
})

test('AC3: error state shows an alert and retry recovers', async () => {
  const list = vi
    .fn<DataSource['listApplications']>()
    .mockRejectedValueOnce(new Error('boom'))
    .mockResolvedValue({ items: [], next_cursor: null })
  const user = userEvent.setup()
  renderWithSource(fakeSource(list), <DashboardPage />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load applications.')
  await user.click(screen.getByRole('button', { name: 'Retry' }))
  expect(await screen.findByRole('heading', { name: 'No applications yet' })).toBeVisible()
})

test('load more fetches the next page using next_cursor', async () => {
  const demo = createDemoDataSource()
  const user = userEvent.setup()
  const paged: DataSource = {
    ...demo,
    listApplications: (p) => demo.listApplications({ ...p, limit: 10 }),
  }
  renderWithSource(paged, <DashboardPage />)
  await user.click(await screen.findByRole('button', { name: 'Load more' }))
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull())
  expect(screen.getAllByRole('link')).toHaveLength(18)
})

test('AC4: subject, snippet and company with markup render as literal text', async () => {
  const demo = createDemoDataSource()
  const id = (await demo.listApplications({})).items[0]!.id
  const evil = {
    ...(await demo.getApplication(id)),
    company: '<img src=x onerror=alert(1)>',
    subject: '<script>alert(1)</script>',
    snippet: '<img src=x onerror=alert(2)>',
  }
  const { container } = renderWithSource(
    { ...demo, getApplication: async () => evil },
    <Routes>
      <Route path="/demo/applications/:id" element={<ApplicationDetailPage />} />
    </Routes>,
    `/demo/applications/${id}`,
  )
  expect(await screen.findByText('<script>alert(1)</script>')).toBeVisible()
  expect(screen.getByText('<img src=x onerror=alert(2)>')).toBeVisible()
  expect(container.querySelector('script, img')).toBeNull()
})

test('AC7: demo routes never call fetch and show the demo banner', async () => {
  const user = userEvent.setup()
  renderRoute('/demo')
  expect(await screen.findByText(/Demo data/)).toBeVisible()
  await user.click(await screen.findByRole('link', { name: /Northwind Labs/ }))
  expect(await screen.findByRole('heading', { name: 'Northwind Labs' })).toBeVisible()
  expect(screen.getByText(/Demo data/)).toBeVisible()
  expect(throwingFetch).not.toHaveBeenCalled()
})

test('AC1: a card with an unknown display_status is shown under its status, or Other', async () => {
  const demo = createDemoDataSource()
  const page = await demo.listApplications({})
  const [a, b] = page.items
  const items = [
    { ...a!, company: 'MysteryCo', display_status: 'future_status', status: 'offer' as const },
    { ...b!, company: 'OddCo', display_status: 'x', status: 'y' as never },
  ]
  renderWithSource(
    fakeSource(async () => ({ next_cursor: 'more', items })),
    <DashboardPage />,
  )
  const offer = (await screen.findByRole('heading', { name: 'Offer (1+)' })).closest('section')!
  expect(within(offer).getByText('MysteryCo')).toBeVisible()
  const other = screen.getByRole('heading', { name: 'Other (1+)' }).closest('section')!
  expect(within(other).getByText('OddCo')).toBeVisible()
})

test('AC5: a status change moves the card on the board immediately', async () => {
  const demo = createDemoDataSource()
  const user = userEvent.setup()
  renderWithSource(
    { ...demo, updateApplication: () => new Promise<never>(() => {}) },
    <Routes>
      <Route path="/demo" element={<DashboardPage />} />
      <Route path="/demo/applications/:id" element={<ApplicationDetailPage />} />
    </Routes>,
    '/demo',
  )
  await user.click(await screen.findByRole('link', { name: /Northwind Labs/ }))
  await user.selectOptions(await screen.findByLabelText('Change status'), 'offer')
  await user.click(await screen.findByRole('link', { name: /Back to applications/ }))
  const offer = (await screen.findByRole('heading', { name: /^Offer/ })).closest('section')!
  expect(within(offer).getByText('Northwind Labs')).toBeVisible()
})
