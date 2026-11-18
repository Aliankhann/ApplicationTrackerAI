import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { ApiError } from './data/dataSource.ts'
import App from './App.tsx'
import './index.css'

const retryUnlessClientError = (count: number, error: unknown) =>
  !(error instanceof ApiError && error.status < 500) && count < 1

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: retryUnlessClientError, refetchOnWindowFocus: false },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
