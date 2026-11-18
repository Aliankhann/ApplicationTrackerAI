import { useId, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  CODE_HINT,
  CODE_PROBLEM_MESSAGES,
  GOOGLE_START_URL,
  messageForError,
  submitInvite,
  validateCode,
} from './signIn'

type Step = 'code' | 'checking' | 'google'

function GoogleLink({ children }: { children: string }) {
  // A plain navigation: the browser leaves for the API, which talks to Google. No tokens in JS.
  return (
    <a href={GOOGLE_START_URL} className="btn inline-block">
      {children}
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
  const [step, setStep] = useState<Step>('code')
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
      <h1 className="text-2xl font-bold">Sign in</h1>
      {message && (
        <p id={messageId} role="alert" className="mt-4 text-red-800 dark:text-red-300">
          {message}
        </p>
      )}
      {step === 'google' ? (
        <section className="mt-6" aria-labelledby="step2">
          <h2 id="step2" className="font-semibold">
            Your code is accepted
          </h2>
          <p className="mt-2 text-gray-700 dark:text-gray-300">
            Now continue with Google to finish signing in. Use the Google account you were invited
            with.
          </p>
          <div className="mt-4">
            <GoogleLink>Continue with Google</GoogleLink>
          </div>
        </section>
      ) : (
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
          <p className="mt-6 text-sm">
            Already have an account? <GoogleLink>Continue with Google</GoogleLink>
          </p>
        </form>
      )}
      <UnverifiedGuide />
      <p className="mt-8 text-sm">
        <Link to="/" className="link">
          Back to home
        </Link>
      </p>
    </main>
  )
}
