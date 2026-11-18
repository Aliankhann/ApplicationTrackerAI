import { screen, waitFor, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ApiError, type DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import ApplicationDetailPage from './ApplicationDetailPage'

beforeEach(() =>
  vi.stubGlobal('fetch', () => {
    throw new Error('no network')
  }),
)
afterEach(() => vi.unstubAllGlobals())

const ID = '00000000-0000-4000-8000-000000000009' // Ashgrove Health: interview, 3-step timeline

function renderDetail(source: DataSource) {
  return renderWithSource(
    source,
    <Routes>
      <Route path="/demo/applications/:id" element={<ApplicationDetailPage />} />
    </Routes>,
    `/demo/applications/${ID}`,
  )
}

test('AC5: timeline is in order with plain-language reasons', async () => {
  renderRoute(`/demo/applications/${ID}`)
  const items = within(await screen.findByRole('list')).getAllByRole('listitem')
  expect(items.map((i) => i.textContent)).toEqual([
    expect.stringMatching(/^Applied \(created,/),
    expect.stringMatching(/^Applied → Online assessment \(detected from email,/),
    expect.stringMatching(/^Online assessment → Interview \(detected from email,/),
  ])
})

test('AC5: changing status calls updateApplication with the payload and updates optimistically', async () => {
  const demo = createDemoDataSource()
  let release: () => void = () => {}
  const update = vi.fn<DataSource['updateApplication']>(async (id, patch) => {
    await new Promise<void>((resolve) => (release = resolve))
    return demo.updateApplication(id, patch)
  })
  const user = userEvent.setup()
  renderDetail({ ...demo, updateApplication: update })
  await user.selectOptions(await screen.findByLabelText('Change status'), 'offer')
  await waitFor(() => expect(update).toHaveBeenCalledWith(ID, { status: 'offer' }))
  // Visible before the server replies.
  expect(await screen.findByText('Locked: you set this manually')).toBeVisible()
  expect(screen.getByLabelText('Change status')).toHaveValue('offer')
  release()
  await waitFor(() => expect(screen.getAllByText(/changed by you/)).toHaveLength(1))
})

test('AC5: on error the status rolls back and an error is shown', async () => {
  const demo = createDemoDataSource()
  const user = userEvent.setup()
  renderDetail({
    ...demo,
    updateApplication: async () => {
      throw new Error('nope')
    },
  })
  await user.selectOptions(await screen.findByLabelText('Change status'), 'rejected')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not save your change')
  expect(screen.getByLabelText('Change status')).toHaveValue('interview')
  expect(screen.queryByText('Locked: you set this manually')).toBeNull()
})

test('AC6: company and role edits validate lengths', async () => {
  const demo = createDemoDataSource()
  const update = vi.fn<DataSource['updateApplication']>(demo.updateApplication)
  const user = userEvent.setup()
  renderDetail({ ...demo, updateApplication: update })
  await user.click(await screen.findByRole('button', { name: 'Edit company and role' }))
  await user.clear(screen.getByLabelText('Company'))
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByText('Company must be 1 to 80 characters.')).toBeVisible()

  await user.type(screen.getByLabelText('Company'), 'x'.repeat(81))
  await user.clear(screen.getByLabelText('Role'))
  await user.type(screen.getByLabelText('Role'), 'y'.repeat(121))
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByText('Company must be 1 to 80 characters.')).toBeVisible()
  expect(screen.getByText('Role must be 1 to 120 characters.')).toBeVisible()
  expect(update).not.toHaveBeenCalled()

  await user.clear(screen.getByLabelText('Company'))
  await user.type(screen.getByLabelText('Company'), 'New Co')
  await user.clear(screen.getByLabelText('Role'))
  await user.type(screen.getByLabelText('Role'), 'New Role')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() =>
    expect(update).toHaveBeenCalledWith(ID, {
      company: 'New Co',
      role: 'New Role',
    }),
  )
  expect(await screen.findByRole('heading', { name: 'New Co' })).toBeVisible()
})

test('AC6: pause toggle calls updateApplication', async () => {
  const demo = createDemoDataSource()
  const update = vi.fn<DataSource['updateApplication']>(demo.updateApplication)
  const user = userEvent.setup()
  renderDetail({ ...demo, updateApplication: update })
  await user.click(await screen.findByRole('button', { name: 'Pause follow-ups' }))
  await waitFor(() => expect(update).toHaveBeenCalledWith(ID, { followups_paused: true }))
  expect(await screen.findByRole('button', { name: 'Resume follow-ups' })).toBeVisible()
})

test('detail shows the needs-review notice', async () => {
  renderRoute('/demo/applications/00000000-0000-4000-8000-000000000011')
  expect(await screen.findByText(/Needs review:/)).toBeVisible()
})

test('404 shows Application not found with a link back', async () => {
  renderRoute('/demo/applications/00000000-0000-4000-8000-0000000000ff')
  expect(await screen.findByRole('heading', { name: 'Application not found' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Back to applications' })).toHaveAttribute(
    'href',
    '/demo',
  )
})

test('AC6: a failed company/role save shows an alert, stays open and keeps the typed values', async () => {
  const demo = createDemoDataSource()
  const user = userEvent.setup()
  renderDetail({
    ...demo,
    updateApplication: async () => {
      throw new ApiError(500, 'boom')
    },
  })
  await user.click(await screen.findByRole('button', { name: /Edit company/ }))
  await user.clear(screen.getByLabelText('Company'))
  await user.type(screen.getByLabelText('Company'), 'NewCo')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(screen.getByLabelText('Company')).toHaveValue('NewCo')
})
