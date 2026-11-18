import type { Page } from '@playwright/test'

export const ORIGIN = 'http://localhost:4173'
export const API_BASE_URL = 'http://localhost:8000'

// Aborts every request that leaves the app origin and returns the URLs that tried to.
export async function blockExternal(page: Page): Promise<string[]> {
  const blocked: string[] = []
  await page.route(
    (url) => !url.href.startsWith(ORIGIN) && url.protocol.startsWith('http'),
    (route) => {
      blocked.push(route.request().url())
      return route.abort()
    },
  )
  return blocked
}

export async function openDemo(page: Page) {
  await page.goto('/')
  await page.getByRole('link', { name: 'Try the demo' }).click()
  await page.getByRole('heading', { name: 'Applications' }).waitFor()
}
