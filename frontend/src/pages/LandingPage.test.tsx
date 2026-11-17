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
