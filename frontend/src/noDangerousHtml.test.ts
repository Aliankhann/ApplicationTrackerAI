import { expect, test } from 'vitest'

const sources = import.meta.glob(['./**/*.{ts,tsx}', '!./**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

test('AC10: no dangerouslySetInnerHTML anywhere in src', () => {
  expect(Object.keys(sources).length).toBeGreaterThan(10)
  const offenders = Object.entries(sources)
    .filter(([, text]) => text.includes('dangerouslySetInnerHTML'))
    .map(([path]) => path)
  expect(offenders).toEqual([])
})
