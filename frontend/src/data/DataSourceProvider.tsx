import type { ReactNode } from 'react'
import type { DataSource } from './dataSource'
import { DataSourceContext } from './context'

export function DataSourceProvider({
  source,
  basePath,
  children,
}: {
  source: DataSource
  basePath: string
  children: ReactNode
}) {
  return <DataSourceContext value={{ source, basePath }}>{children}</DataSourceContext>
}
