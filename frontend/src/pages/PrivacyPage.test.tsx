import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
import { CONTACT_MAILTO, GOOGLE_PERMISSIONS_URL } from '../constants'
import PrivacyPage from './PrivacyPage'

afterEach(() => vi.unstubAllGlobals())

function renderPage() {
  const fetchSpy = vi.fn()
  vi.stubGlobal('fetch', fetchSpy)
  const view = render(
    <MemoryRouter>
      <PrivacyPage />
    </MemoryRouter>,
  )
  return { ...view, fetchSpy }
}

test('US-81: renders every key section as an accessible heading', () => {
  renderPage()
  expect(screen.getByRole('heading', { level: 1, name: 'Privacy' })).toBeInTheDocument()
  for (const name of [
    'What we read from Gmail',
    'What we store',
    'What goes to the AI model',
    'Follow-up drafts and digest emails',
    'Who can access your data',
    'Security',
    'Deleting your data',
    'Contact',
  ]) {
    expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument()
  }
})

test('US-81: states the gmail.compose honesty note and that drafts are the only thing created', () => {
  const { container } = renderPage()
  const text = container.textContent ?? ''
  expect(text).toContain('gmail.readonly')
  expect(text).toContain('gmail.compose')
  expect(text).toMatch(/technically allows .*sending/)
  expect(text).toMatch(/only ever creates drafts/)
})

test('US-81: marks undecided values as visible TODOs and shows the last updated date', () => {
  const { container } = renderPage()
  const text = container.textContent ?? ''
  expect(text).toMatch(/TODO: backup retention window/)
  expect(text).toMatch(/TODO: contact email/)
  expect(text).toMatch(/TODO: link Anthropic's data terms/)
  expect(text).toMatch(/Last updated: \d{4}-\d{2}-\d{2}/)
})

test('US-81: makes no network call and has no scripts or other external links', () => {
  const { container, fetchSpy } = renderPage()
  expect(fetchSpy).not.toHaveBeenCalled()
  expect(container.querySelectorAll('script, iframe, img, link, form')).toHaveLength(0)
  const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
  const external = hrefs.filter((h) => h !== null && !h.startsWith('/'))
  expect(new Set(external)).toEqual(new Set([GOOGLE_PERMISSIONS_URL, CONTACT_MAILTO]))
})
