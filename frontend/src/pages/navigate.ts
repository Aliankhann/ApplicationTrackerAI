const GOOGLE_HOST = 'accounts.google.com'

export function isGoogleAuthorizeUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === GOOGLE_HOST && url.port === ''
  } catch {
    return false
  }
}

// Full-page navigation to Google's consent screen only; anything else is refused.
export function navigateTo(url: string): void {
  if (!isGoogleAuthorizeUrl(url)) throw new Error('Refusing to navigate to a non-Google address')
  window.location.assign(url)
}
