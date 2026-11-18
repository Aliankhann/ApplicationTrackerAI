import { expect, test } from '@playwright/test'
import { API_BASE_URL, blockExternal } from './helpers.ts'

const COLUMNS = ['Applied', 'Online assessment', 'Interview', 'Offer', 'Rejected', 'Ghosted']

test('demo flow works end to end with no requests leaving the origin', async ({ page }) => {
  const blocked = await blockExternal(page)
  const apiCalls: string[] = []
  page.on('request', (r) => {
    if (r.url().startsWith(API_BASE_URL)) apiCalls.push(r.url())
  })

  await page.goto('/')
  await expect(page.getByText(/The demo shows the board/)).toBeVisible()
  await page.getByRole('link', { name: 'Try the demo' }).click()
  await expect(page.getByRole('region', { name: 'Demo notice' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Exit demo' })).toBeVisible()
  apiCalls.length = 0 // the landing page may check API health; the demo itself must not

  // Board shows every column.
  for (const label of COLUMNS) {
    await expect(
      page.getByRole('heading', {
        level: 2,
        name: new RegExp(`^${label} \\(`),
      }),
    ).toBeVisible()
  }
  await expect(page.getByRole('button', { name: 'Connect Gmail' })).toBeDisabled()

  // Table view and sorting.
  await page.getByText('Table', { exact: true }).click()
  const rows = page.getByRole('row')
  await expect(rows.nth(1)).toBeVisible()
  const firstRow = () => rows.nth(1).innerText()
  const before = await firstRow()
  await page.getByLabel('Sort by').selectOption('last_activity:asc')
  await expect.poll(firstRow).not.toBe(before)

  // Detail and status change update in place.
  await page.getByRole('link', { name: 'Northwind Labs' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Northwind Labs' })).toBeVisible()
  await page.getByLabel('Change status').selectOption('offer')
  await expect(page.getByText('Locked: you set this manually')).toBeVisible()
  await expect(page.getByLabel('Change status')).toHaveValue('offer')

  // Follow-ups: skip a scheduled one.
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Follow-ups' })
    .click()
  await expect(page.getByRole('heading', { name: 'Scheduled' })).toBeVisible()
  const skips = page.getByRole('button', { name: 'Skip' })
  const count = await skips.count()
  expect(count).toBeGreaterThan(0)
  await skips.first().click()
  await expect(skips).toHaveCount(count - 1)

  // Settings: editing a template updates the preview.
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Settings' })
    .click()
  await page.getByRole('link', { name: 'Follow-up settings' }).click()
  const template = page.getByLabel('Template for step 1')
  await template.fill('Hello, checking in about the {role} role at {company}. Zebra marker.')
  await expect(page.getByRole('region', { name: 'Step 1 preview' })).toContainText('Zebra marker')

  // Data controls are disabled.
  await page
    .getByRole('navigation', { name: 'Main' })
    .getByRole('link', { name: 'Settings' })
    .click()
  await expect(page.getByRole('button', { name: 'Connect Gmail' })).toBeDisabled()
  await expect(page.getByRole('button', { name: /Disconnect Gmail/ })).toBeDisabled()
  await expect(page.getByRole('button', { name: /Delete/ })).toBeDisabled()

  // Everything inside the demo stayed offline.
  expect(apiCalls).toEqual([])
  expect(blocked.filter((u) => !u.startsWith(API_BASE_URL))).toEqual([])

  // Exit demo returns to the landing page (which may check API health again).
  await page.getByRole('link', { name: 'Exit demo' }).click()
  await expect(page.getByRole('heading', { name: 'Application Tracker' })).toBeVisible()
})
