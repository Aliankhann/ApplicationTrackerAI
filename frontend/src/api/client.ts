import createClient from 'openapi-fetch'
import { z } from 'zod'
import type { paths } from './schema'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

// Typed against the backend's OpenAPI schema. Regenerate with `pnpm gen:api`.
// credentials: 'include' sends the session cookie; tokens never live in localStorage.
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  credentials: 'include',
  // Resolve fetch at call time so tests can stub it.
  fetch: (request) => globalThis.fetch(request),
})

export const HealthSchema = z.object({ status: z.string() })
export type Health = z.infer<typeof HealthSchema>

export async function fetchHealth(): Promise<Health> {
  const { data, error } = await api.GET('/health')
  if (error || !data) throw new Error('API is unreachable')
  return HealthSchema.parse(data)
}
