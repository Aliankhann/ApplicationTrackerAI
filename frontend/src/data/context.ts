import { createContext, useContext } from 'react'
import type { DataSource } from './dataSource'

export interface DataSourceValue {
  source: DataSource
  basePath: string
}

export const DataSourceContext = createContext<DataSourceValue | null>(null)

export function useDataSourceValue(): DataSourceValue {
  const value = useContext(DataSourceContext)
  if (!value) throw new Error('useDataSource must be used inside DataSourceProvider')
  return value
}

export function useDataSource(): DataSource {
  return useDataSourceValue().source
}

export function useBasePath(): string {
  return useDataSourceValue().basePath
}
