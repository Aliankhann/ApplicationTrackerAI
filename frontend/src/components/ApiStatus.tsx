import { useQuery } from '@tanstack/react-query'
import { fetchHealth } from '../api/client'

export default function ApiStatus() {
  const { data, isPending, isError } = useQuery({ queryKey: ['health'], queryFn: fetchHealth })

  if (isPending) return <p className="text-sm text-gray-500">Checking API…</p>
  if (isError) return <p className="text-sm text-red-700">API unreachable</p>
  return <p className="text-sm text-green-700">API status: {data.status}</p>
}
