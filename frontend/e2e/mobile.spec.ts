import { expect, test } from '@playwright/test'
import { blockExternal, openDemo } from './helpers.ts'

test.use({ viewport: { width: 390, height: 844 } })

const noHorizontalScroll = (page: import('@playwright/test').Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)

test('demo board and detail do not scroll horizontally on a phone', async ({ page }) => {
  await blockExternal(page)
  await openDemo(page)
  await expect(page.getByRole('link', { name: /Northwind Labs/ })).toBeVisible()
  expect(await noHorizontalScroll(page)).toBe(true)

  await page.getByRole('link', { name: /Northwind Labs/ }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Northwind Labs' })).toBeVisible()
  expect(await noHorizontalScroll(page)).toBe(true)
})
