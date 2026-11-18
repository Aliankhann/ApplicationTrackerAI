import { Link } from 'react-router'

export default function SignInPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Sign in</h1>
      <p className="mt-4 text-gray-700 dark:text-gray-300">
        Sign-in is not available yet. You can explore the app with sample data instead.
      </p>
      <Link to="/demo" className="btn mt-6 inline-block">
        Try the demo
      </Link>
    </main>
  )
}
