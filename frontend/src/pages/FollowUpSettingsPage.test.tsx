import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { apiDataSource } from '../data/apiDataSource'
import { ApiError, type DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderRoute, renderWithSource } from '../test/render'
import userEvent from '../test/user'
import FollowUpSettingsPage from './FollowUpSettingsPage'

const throwingFetch = vi.fn(() => {
  throw new Error('network is forbidden in demo mode')
})
beforeEach(() => vi.stubGlobal('fetch', throwingFetch))
afterEach(() => {
  throwingFetch.mockClear()
  vi.unstubAllGlobals()
})

const setValue = async (user: ReturnType<typeof userEvent.setup>, label: string, value: string) => {
  const input = screen.getByLabelText(label)
  await user.clear(input)
  if (value) await user.type(input, value)
}

test('US-61: demo settings load the default sequence with placeholder help, no fetch', async () => {
  renderRoute('/demo/settings/follow-ups')
  expect(await screen.findByLabelText('Delay (days) for step 1')).toHaveValue(7)
  expect(screen.getByText(/\{recruiter_first_name\}/)).toBeVisible()
  expect(throwingFetch).not.toHaveBeenCalled()
})

test('US-61: live preview renders the template with sample data and the chosen tone', async () => {
  const user = userEvent.setup()
  renderRoute('/demo/settings/follow-ups')
  await screen.findByLabelText('Template for step 1')
  expect(await screen.findByLabelText('Step 1 preview')).toHaveTextContent('Hi Alex,')
  await user.selectOptions(screen.getByLabelText('Tone'), 'formal')
  await waitFor(() =>
    expect(screen.getByLabelText('Step 1 preview')).toHaveTextContent('Dear Alex,'),
  )
  expect(screen.getByLabelText('Step 1 preview')).toHaveTextContent('Software Engineering Intern')
})

test('US-61: client validation blocks save and shows field messages', async () => {
  const demo = createDemoDataSource()
  const update = vi.fn<DataSource['updateSequence']>(demo.updateSequence)
  const user = userEvent.setup()
  renderWithSource({ ...demo, updateSequence: update }, <FollowUpSettingsPage />)
  await screen.findByLabelText('Template for step 1')
  await setValue(user, 'Delay (days) for step 2', '3')
  await setValue(user, 'Delay (days) for step 1', '99')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByText('Delay must be 1 to 60 days.')).toBeVisible()
  expect(screen.getByText('Delay must be later than the previous step.')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Template for step 1'), {
    target: { value: 'Hi there {bogus}' },
  })
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(screen.getByText('Unknown placeholder {bogus}.')).toBeVisible()
  expect(update).not.toHaveBeenCalled()
})

test('US-61: add and remove steps within 1 to 5, then save sends the steps', async () => {
  const demo = createDemoDataSource()
  const update = vi.fn<DataSource['updateSequence']>(demo.updateSequence)
  const user = userEvent.setup()
  renderWithSource({ ...demo, updateSequence: update }, <FollowUpSettingsPage />)
  await screen.findByLabelText('Template for step 1')
  for (let i = 0; i < 3; i++) await user.click(screen.getByRole('button', { name: 'Add step' }))
  expect(screen.getByRole('button', { name: 'Add step' })).toBeDisabled()
  for (let i = 5; i > 1; i--)
    await user.click(screen.getByRole('button', { name: `Remove step ${i}` }))
  expect(screen.queryByRole('button', { name: /Remove step/ })).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(update).toHaveBeenCalled())
  expect(update.mock.calls[0]![1].steps).toHaveLength(1)
  expect(await screen.findByRole('status')).toHaveTextContent('Saved')
})

test('US-61: save is disabled while pending', async () => {
  const demo = createDemoDataSource()
  const user = userEvent.setup()
  renderWithSource(
    { ...demo, updateSequence: () => new Promise(() => {}) },
    <FollowUpSettingsPage />,
  )
  await screen.findByLabelText('Template for step 1')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('button', { name: 'Saving' })).toBeDisabled()
})

test('US-61: server 422 messages are shown next to their fields', async () => {
  const demo = createDemoDataSource()
  const update = async () => {
    throw new ApiError(422, 'bad', [
      { field: 'steps.1.template', code: 'invalid_template', message: 'Server says no to step 2' },
      { field: 'tone', code: 'invalid_tone', message: 'Server dislikes the tone' },
    ])
  }
  const user = userEvent.setup()
  renderWithSource({ ...demo, updateSequence: update }, <FollowUpSettingsPage />)
  await screen.findByLabelText('Template for step 1')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Server says no to step 2')).toBeVisible()
  expect(screen.getByText('Server dislikes the tone')).toBeVisible()
})

test('US-61: apiDataSource turns a 422 body into field errors and sends the CSRF-bound PATCH', async () => {
  const detail = [{ field: 'steps.0.template', code: 'invalid_template', message: 'Bad template' }]
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ detail }, { status: 422 })),
  )
  const error = await apiDataSource
    .updateSequence('00000000-0000-4000-8000-000000000001', { tone: 'warm' })
    .catch((e: unknown) => e)
  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).fieldErrors).toEqual(detail)
})

test('US-61: invisible and control characters are rejected client-side', async () => {
  const demo = createDemoDataSource()
  const update = vi.fn<DataSource['updateSequence']>(demo.updateSequence)
  const user = userEvent.setup()
  renderWithSource({ ...demo, updateSequence: update }, <FollowUpSettingsPage />)
  fireEvent.change(await screen.findByLabelText('Template for step 1'), {
    target: { value: 'Hi\u200b there' },
  })
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(
    screen.getByText('Templates may not contain control or invisible characters.'),
  ).toBeVisible()
  expect(update).not.toHaveBeenCalled()
  expect(screen.getByRole('region', { name: 'Step 1 preview' })).toHaveAttribute(
    'aria-live',
    'polite',
  )
})
