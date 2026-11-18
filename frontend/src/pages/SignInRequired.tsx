import { Link } from 'react-router'

// Shown inside /app when the API answers 401.
export default function SignInRequired() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Sign in</h1>
      <p className="mt-4 text-gray-700 dark:text-gray-300">
        You need to sign in to see your applications. You can also explore with sample data.
      </p>
      <div className="mt-6 flex gap-4">
        <Link to="/sign-in" className="btn inline-block">
          Go to sign in
        </Link>
        <Link to="/demo" className="link inline-block self-center">
          Try the demo
        </Link>
      </div>
    </main>
  )
}
