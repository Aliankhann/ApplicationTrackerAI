import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { blockExternal, openDemo } from './helpers.ts'

const PAGES = [
  ['board', '/demo'],
  ['detail', null],
  ['follow-ups', '/demo/follow-ups'],
  ['settings', '/demo/settings'],
  ['follow-up settings', '/demo/settings/follow-ups'],
] as const

for (const [name, path] of PAGES) {
  test(`demo ${name} page has no serious or critical accessibility violations`, async ({
    page,
  }) => {
    await blockExternal(page)
    await openDemo(page)
    if (path) await page.getByRole('navigation', { name: 'Main' }).waitFor()
    if (path) await page.goto(path)
    else await page.getByRole('link', { name: 'Northwind Labs' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const { violations } = await new AxeBuilder({ page }).analyze()
    const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(
      serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`),
    ).toEqual([])

    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    expect(await page.locator('[tabindex]:not([tabindex="0"]):not([tabindex^="-"])').count()).toBe(
      0,
    )
  })
}

test('keyboard only: Tab reaches a board card and Enter opens it', async ({ page }) => {
  await blockExternal(page)
  await openDemo(page)
  const card = page.getByRole('link', { name: /Northwind Labs/ })
  await expect(card).toBeVisible()
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab')
    if (await card.evaluate((el) => el === document.activeElement)) break
  }
  await expect(card).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { level: 1, name: 'Northwind Labs' })).toBeVisible()
})
