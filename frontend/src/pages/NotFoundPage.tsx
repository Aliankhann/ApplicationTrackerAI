import { Link } from 'react-router'

export default function NotFoundPage() {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16">
      <h1 className="text-2xl font-bold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block underline">
        Back home
      </Link>
    </main>
  )
}
