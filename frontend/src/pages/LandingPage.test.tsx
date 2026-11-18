import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'
import LandingPage from './LandingPage'

afterEach(() => vi.unstubAllGlobals())

test('renders the pitch and reports API health', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByRole('heading', { name: 'Application Tracker' })).toBeInTheDocument()
  expect(await screen.findByText('API status: ok')).toBeInTheDocument()
})

test('US-81: footer links to the privacy page', () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByRole('link', { name: 'Privacy' })).toHaveAttribute('href', '/privacy')
})

test('US-100: the landing page says what the demo shows', () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok' })),
  )
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <LandingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByText(/The demo shows the board/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Try the demo' })).toHaveAttribute('href', '/demo')
})
