import createClient, { type Middleware } from 'openapi-fetch'
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

// __Host- is used by the backend outside local when no cookie domain is configured.
const CSRF_COOKIES = ['__Host-tracker_csrf', 'tracker_csrf']
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export function readCookie(name: string): string | undefined {
  const prefix = `${name}=`
  const hit = document.cookie.split('; ').find((part) => part.startsWith(prefix))
  return hit ? decodeURIComponent(hit.slice(prefix.length)) : undefined
}

// The CSRF cookie is readable by design; the server checks the header against the session.
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    const token = CSRF_COOKIES.map(readCookie).find(Boolean)
    if (!SAFE_METHODS.has(request.method) && token) request.headers.set('X-CSRF-Token', token)
    return request
  },
}
api.use(csrfMiddleware)

export const HealthSchema = z.object({ status: z.string() })
export type Health = z.infer<typeof HealthSchema>

export async function fetchHealth(): Promise<Health> {
  const { data, error } = await api.GET('/health')
  if (error || !data) throw new Error('API is unreachable')
  return HealthSchema.parse(data)
}
