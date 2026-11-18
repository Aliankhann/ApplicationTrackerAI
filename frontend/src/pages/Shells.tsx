import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router'
import { apiDataSource } from '../data/apiDataSource'
import { DataSourceProvider } from '../data/DataSourceProvider'
import { createDemoDataSource } from '../data/demoDataSource'

export function ApiShell() {
  return (
    <DataSourceProvider source={apiDataSource} basePath="/app">
      <Outlet />
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
        Demo data: sample applications, nothing is saved or sent.
      </div>
      <Outlet />
    </DataSourceProvider>
  )
}
