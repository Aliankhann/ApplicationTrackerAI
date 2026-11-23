import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router'
import { apiDataSource } from '../data/apiDataSource'
import { DataSourceProvider } from '../data/DataSourceProvider'
import { createDemoDataSource } from '../data/demoDataSource'
import { useMe } from '../data/hooks'
import FinishSetupPage from './FinishSetupPage'

function Nav({ basePath }: { basePath: string }) {
  const links = [
    [basePath, 'Applications'],
    [`${basePath}/follow-ups`, 'Follow-ups'],
    [`${basePath}/settings`, 'Settings'],
  ] as const
  return (
    <nav aria-label="Main" className="flex gap-4 border-b px-4 py-2">
      {links.map(([to, label]) => (
        <NavLink key={to} to={to} end className="link">
          {label}
        </NavLink>
      ))}
    </nav>
  )
}

// An invited user who has not connected Gmail yet only sees the finish-setup screen. If /me
// fails (for example a 401), the pages themselves show the error.
function SetupGate() {
  const me = useMe()
  if (me.isPending) return null
  if (me.data && !me.data.setup_completed) return <FinishSetupPage me={me.data} />
  return (
    <>
      <Nav basePath="/app" />
      <Outlet />
    </>
  )
}

export function ApiShell() {
  return (
    <DataSourceProvider source={apiDataSource} basePath="/app">
      <SetupGate />
    </DataSourceProvider>
  )
}

export function DemoShell() {
  const [source] = useState(() => createDemoDataSource())
  const client = useQueryClient()
  // A fresh demo source must never show cached data from a previous one.
  useEffect(
    () => () => client.removeQueries({ predicate: (q) => q.queryKey[1] === 'demo' }),
    [client],
  )
  return (
    <DataSourceProvider source={source} basePath="/demo">
      <div
        role="region"
        aria-label="Demo notice"
        className="bg-amber-100 px-4 py-2 text-center text-sm text-amber-950"
      >
        Demo data: sample applications, nothing is saved or sent.{' '}
        <Link to="/" className="font-semibold underline">
          Exit demo
        </Link>
      </div>
      <Nav basePath="/demo" />
      <Outlet />
    </DataSourceProvider>
  )
}
