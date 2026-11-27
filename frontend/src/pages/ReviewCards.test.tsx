import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderWithSource } from '../test/render'
import userEvent from '../test/user'
import ApplicationDetailPage from './ApplicationDetailPage'
import DashboardPage from './DashboardPage'

beforeEach(() =>
  vi.stubGlobal('fetch', () => {
    throw new Error('no network')
  }),
)
afterEach(() => vi.unstubAllGlobals())

async function reviewCard(demo = createDemoDataSource(), suggested = 'interview') {
  const page = await demo.listApplications({ status: 'needs_review' })
  const card = page.items.find((a) => a.suggested_label === suggested)
  if (!card) throw new Error('no such review card')
  return { demo, id: card.id }
}

function renderDetail(demo: ReturnType<typeof createDemoDataSource>, id: string) {
  return renderWithSource(
    demo,
    <Routes>
      <Route path="/demo" element={<p>Board home</p>} />
      <Route path="/demo/applications/:id" element={<ApplicationDetailPage />} />
    </Routes>,
    `/demo/applications/${id}`,
  )
}

test('the board shows a Needs review column with the suggested label on the card', async () => {
  const user = userEvent.setup()
  renderWithSource(createDemoDataSource(), <DashboardPage />, '/demo')
  await user.click(await screen.findByRole('radio', { name: 'Board view' }))
  expect(await screen.findByRole('heading', { name: /Needs review/ })).toBeVisible()
  expect(screen.getByText('Suggested: Interview')).toBeVisible()
})

test('Confirm applies the suggestion and the card leaves review', async () => {
  const { demo, id } = await reviewCard()
  const user = userEvent.setup()
  renderDetail(demo, id)
  await user.click(await screen.findByRole('button', { name: 'Confirm Interview' }))
  await waitFor(() => expect(screen.queryByRole('note', { name: 'Needs review' })).toBeNull())
  expect((await demo.getApplication(id)).status).toBe('interview')
  expect((await demo.getApplication(id)).needs_review).toBe(false)
})

test('Change status sets it by hand and clears the review state', async () => {
  const { demo, id } = await reviewCard()
  const user = userEvent.setup()
  renderDetail(demo, id)
  await user.selectOptions(await screen.findByLabelText('Change status'), 'offer')
  await waitFor(() => expect(screen.queryByRole('note', { name: 'Needs review' })).toBeNull())
  const detail = await demo.getApplication(id)
  expect([detail.status, detail.needs_review]).toEqual(['offer', false])
})

test('Dismiss hides the card and returns to the board', async () => {
  const { demo, id } = await reviewCard()
  const user = userEvent.setup()
  renderDetail(demo, id)
  await user.click(await screen.findByRole('button', { name: 'Dismiss' }))
  expect(await screen.findByText('Board home')).toBeVisible()
  await expect(demo.getApplication(id)).rejects.toMatchObject({ status: 404 })
})

test('a review card without a suggestion offers no Confirm button', async () => {
  const demo = createDemoDataSource()
  const page = await demo.listApplications({ status: 'needs_review' })
  const bare = page.items.find((a) => a.suggested_label === null)
  if (!bare) throw new Error('demo needs a card without a suggestion')
  renderDetail(demo, bare.id)
  expect(await screen.findByText(/There is no suggestion/)).toBeVisible()
  expect(screen.queryByRole('button', { name: /^Confirm/ })).toBeNull()
  expect(screen.getByRole('button', { name: 'Dismiss' })).toBeVisible()
})
