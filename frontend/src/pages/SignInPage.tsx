import { useId, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  CODE_HINT,
  CODE_PROBLEM_MESSAGES,
  googleStartUrl,
  messageForError,
  type AuthMode,
  submitInvite,
  validateCode,
} from './signIn'

type Step = 'choose' | 'signin' | 'code' | 'checking' | 'google'

// Errors that only make sense while signing up open the sign-up step directly.
const SIGN_UP_ERRORS = new Set(['not_invited', 'invite_in_use', 'invite_expired'])

function GoogleLink({ mode }: { mode: AuthMode }) {
  // A plain navigation: the browser leaves for the API, which talks to Google. No tokens in JS.
  return (
    <a href={googleStartUrl(mode)} className="btn inline-block">
      Continue with Google
    </a>
  )
}

function UnverifiedGuide() {
  return (
    <section aria-labelledby="unverified-heading" className="mt-10 rounded border p-4">
      <h2 id="unverified-heading" className="font-semibold">
        If Google says it hasn&apos;t verified this app
      </h2>
      <p className="mt-2 text-sm text-gray-700 dark:text-gray-300">
        This app is invite-only and still unverified by Google, so you will see a warning. It is
        expected. Follow these steps:
      </p>
      <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
        <li>Click &quot;Advanced&quot; on the warning screen.</li>
        <li>Click &quot;Go to Application Tracker (unsafe)&quot;.</li>
        <li>Review the permissions, then click &quot;Continue&quot;.</li>
      </ol>
    </section>
  )
}

export default function SignInPage() {
  const [params] = useSearchParams()
  const [code, setCode] = useState('')
  const [step, setStep] = useState<Step>(() =>
    SIGN_UP_ERRORS.has(params.get('error') ?? '') ? 'code' : 'choose',
  )
  const [problem, setProblem] = useState<string | null>(null)
  const inputId = useId()
  const messageId = useId()
  const urlError = messageForError(params.get('error'))
  const message = problem ?? urlError

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const invalid = validateCode(code)
    if (invalid) return setProblem(CODE_PROBLEM_MESSAGES[invalid])
    setProblem(null)
    setStep('checking')
    const failure = await submitInvite(code)
    if (failure) {
      setProblem(messageForError(failure))
      setStep('code')
    } else {
      setStep('google')
    }
  }

  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Sign up or sign in</h1>
      {message && (
        <p id={messageId} role="alert" className="mt-4 text-red-800 dark:text-red-300">
          {message}
        </p>
      )}
      {step === 'choose' && (
        <div className="mt-6 flex gap-4">
          <button type="button" className="btn" onClick={() => setStep('code')}>
            Sign up
          </button>
          <button type="button" className="btn" onClick={() => setStep('signin')}>
            Sign in
          </button>
        </div>
      )}
      {step === 'signin' && (
        <section className="mt-6" aria-labelledby="signin-heading">
          <h2 id="signin-heading" className="font-semibold">
            Sign in
          </h2>
          <p className="mt-2 text-gray-700 dark:text-gray-300">
            Use the Google account you signed up with. You do not need an invite code.
          </p>
          <div className="mt-4">
            <GoogleLink mode="signin" />
          </div>
        </section>
      )}
      {step === 'google' && (
        <section className="mt-6" aria-labelledby="step2">
          <h2 id="step2" className="font-semibold">
            Your code is accepted
          </h2>
          <p className="mt-2 text-gray-700 dark:text-gray-300">
            Now continue with Google to create your account. Your code is held for you for a few
            minutes; after that you have 24 hours to connect Gmail and finish setup.
          </p>
          <div className="mt-4">
            <GoogleLink mode="signup" />
          </div>
        </section>
      )}
      {(step === 'code' || step === 'checking') && (
        <form onSubmit={onSubmit} noValidate className="mt-6" aria-labelledby="step1">
          <h2 id="step1" className="font-semibold">
            Enter your invite code
          </h2>
          <label htmlFor={inputId} className="mt-3 block text-sm">
            Invite code
          </label>
          <input
            id={inputId}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={CODE_HINT}
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            aria-invalid={problem ? true : undefined}
            aria-describedby={problem ? messageId : undefined}
            className="mt-1 w-full rounded border px-3 py-2 font-mono"
          />
          <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">Format: {CODE_HINT}</p>
          <button type="submit" disabled={step === 'checking'} className="btn mt-4">
            {step === 'checking' ? 'Checking...' : 'Check code'}
          </button>
          {step === 'checking' && (
            <span role="status" className="sr-only">
              Checking your code
            </span>
          )}
        </form>
      )}
      <UnverifiedGuide />
      {(step === 'code' || step === 'signin') && (
        <p className="mt-6 text-sm">
          <button type="button" className="link" onClick={() => setStep('choose')}>
            Back
          </button>
        </p>
      )}
      <p className="mt-8 text-sm">
        <Link to="/" className="link">
          Back to home
        </Link>
      </p>
    </main>
  )
}
