import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'
import App from '../App'
import { DataSourceProvider } from '../data/DataSourceProvider'
import type { DataSource } from '../data/dataSource'

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

export function renderRoute(route: string) {
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

export function renderWithSource(source: DataSource, ui: ReactNode, route = '/demo') {
  return render(
    <QueryClientProvider client={newClient()}>
      <MemoryRouter initialEntries={[route]}>
        <DataSourceProvider source={source} basePath="/demo">
          {ui}
        </DataSourceProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
