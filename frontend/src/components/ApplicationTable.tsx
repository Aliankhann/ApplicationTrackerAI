import { Link } from 'react-router'
import type { Application } from '../data/schemas'
import { useBasePath } from '../data/context'
import { Badges } from './ApplicationCard'
import { relativeDate, shortDate, statusLabel } from './format'

export function ApplicationTable({ items }: { items: Application[] }) {
  const base = useBasePath()
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Applications</caption>
        <thead>
          <tr className="border-b border-gray-300 dark:border-gray-700">
            <th scope="col" className="p-2">
              Company
            </th>
            <th scope="col" className="p-2">
              Role
            </th>
            <th scope="col" className="p-2">
              Status
            </th>
            <th scope="col" className="p-2">
              Applied
            </th>
            <th scope="col" className="p-2">
              Last activity
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((app) => (
            <tr key={app.id} className="border-b border-gray-200 dark:border-gray-800">
              <td className="p-2">
                <Link to={`${base}/applications/${app.id}`} className="link">
                  {app.company ?? 'Unknown company'}
                </Link>
              </td>
              <td className="p-2">{app.role ?? 'Role not detected'}</td>
              <td className="p-2">
                <span className="mr-1">{statusLabel(app.display_status)}</span>
                <Badges app={app} />
              </td>
              <td className="p-2">{shortDate(app.applied_at)}</td>
              <td className="p-2">{relativeDate(app.last_activity_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
