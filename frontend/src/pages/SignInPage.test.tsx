import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { renderRoute } from '../test/render'
import { CODE_HINT, ERROR_MESSAGES, formatCode, normalizeCode, validateCode } from './signIn'

afterEach(() => vi.unstubAllGlobals())

const VALID = 'ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ23-4567'

function stubFetch(status: number) {
  const fn = vi.fn(async (_request: Request) => new Response(null, { status }))
  vi.stubGlobal('fetch', fn)
  return fn
}

const enter = (value: string) =>
  fireEvent.change(screen.getByLabelText('Invite code'), { target: { value } })
const submit = () => fireEvent.click(screen.getByRole('button', { name: 'Check code' }))

test('AC: codes are trimmed, uppercased, and stripped of spaces and hyphens', () => {
  expect(normalizeCode('  abcd-efgh ijkl  ')).toBe('ABCDEFGHIJKL')
  expect(formatCode('abcdefgh')).toBe('ABCD-EFGH')
})

test('AC: code validation reports empty, wrong characters, and wrong length', () => {
  expect(validateCode('   ')).toBe('empty')
  expect(validateCode('ABCD-0000')).toBe('characters')
  expect(validateCode('ABCD-EFGH')).toBe('length')
  expect(validateCode(VALID.toLowerCase())).toBeNull()
})

test('AC: the form shows the format hint and rejects a malformed code without calling the API', async () => {
  const fetchMock = stubFetch(204)
  renderRoute('/sign-in')
  expect(screen.getByRole('heading', { name: 'Enter your invite code' })).toBeVisible()
  expect(screen.getByLabelText('Invite code')).toHaveAttribute('placeholder', CODE_HINT)
  enter('ABCD')
  submit()
  expect(await screen.findByRole('alert')).toHaveTextContent('looks incomplete')
  expect(fetchMock).not.toHaveBeenCalled()
})

test('AC: a good code is posted with credentials and no CSRF cookie, then step 2 appears', async () => {
  const fetchMock = stubFetch(204)
  renderRoute('/sign-in')
  enter(VALID.toLowerCase().replaceAll('-', ' '))
  submit()
  expect(await screen.findByRole('heading', { name: 'Your code is accepted' })).toBeVisible()
  const request = fetchMock.mock.calls[0][0]
  expect(request.url).toMatch(/\/auth\/invite$/)
  expect(request.method).toBe('POST')
  expect(request.credentials).toBe('include')
  expect(request.headers.get('X-CSRF-Token')).toBeNull()
  expect(await request.json()).toEqual({ code: VALID })
})

test('AC: a 400 shows the plain-language invalid code message and keeps the form', async () => {
  stubFetch(400)
  renderRoute('/sign-in')
  enter(VALID)
  submit()
  expect(await screen.findByRole('alert')).toHaveTextContent(ERROR_MESSAGES.invalid_invite)
  expect(screen.getByLabelText('Invite code')).toHaveAttribute('aria-invalid', 'true')
})

test.each([
  [429, 'rate_limited'],
  [503, 'sign_in_unavailable'],
  [500, 'sign_in_failed'],
])('AC: HTTP %i shows the %s message', async (status, code) => {
  stubFetch(status)
  renderRoute('/sign-in')
  enter(VALID)
  submit()
  expect(await screen.findByRole('alert')).toHaveTextContent(ERROR_MESSAGES[code])
})

test('AC: a network failure shows the generic error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('network down')
    }),
  )
  renderRoute('/sign-in')
  enter(VALID)
  submit()
  expect(await screen.findByRole('alert')).toHaveTextContent(ERROR_MESSAGES.sign_in_failed)
})

test('AC: the button is disabled and a status is announced while checking', async () => {
  let release: (r: Response) => void = () => {}
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
  )
  renderRoute('/sign-in')
  enter(VALID)
  fireEvent.click(screen.getByRole('button', { name: 'Check code' }))
  expect(await screen.findByRole('button', { name: 'Checking...' })).toBeDisabled()
  expect(screen.getByRole('status')).toHaveTextContent('Checking your code')
  release(new Response(null, { status: 204 }))
  await waitFor(() => expect(screen.getByText('Your code is accepted')).toBeVisible())
})

test.each(Object.keys(ERROR_MESSAGES))('AC: ?error=%s shows its message', async (code) => {
  renderRoute(`/sign-in?error=${code}`)
  expect(await screen.findByRole('alert')).toHaveTextContent(ERROR_MESSAGES[code])
})

test('AC: an unknown ?error= code falls back to the generic message', async () => {
  renderRoute('/sign-in?error=whatever')
  expect(await screen.findByRole('alert')).toHaveTextContent(ERROR_MESSAGES.sign_in_failed)
})

test('AC: the Google step is a plain navigation link, with no token handling or fetch', async () => {
  const fetchMock = stubFetch(204)
  renderRoute('/sign-in')
  const returning = screen.getByRole('link', { name: 'Continue with Google' })
  expect(returning).toHaveAttribute('href', expect.stringMatching(/\/auth\/google\/start$/))
  enter(VALID)
  submit()
  await screen.findByText('Your code is accepted')
  const link = screen.getByRole('link', { name: 'Continue with Google' })
  expect(link.tagName).toBe('A')
  expect(link).toHaveAttribute('href', returning.getAttribute('href'))
  const calls = fetchMock.mock.calls.length
  link.addEventListener('click', (e) => e.preventDefault())
  fireEvent.click(link)
  expect(fetchMock.mock.calls.length).toBe(calls)
})

test('AC: the unverified-app guide has three steps', () => {
  renderRoute('/sign-in')
  const guide = screen.getByRole('region', { name: /hasn.t verified this app/i })
  expect(guide.querySelectorAll('ol > li')).toHaveLength(3)
})
