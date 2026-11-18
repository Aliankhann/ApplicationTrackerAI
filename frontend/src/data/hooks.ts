import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { useDataSource } from './context'
import type {
  Application,
  ApplicationDetail,
  ApplicationPage,
  ApplicationPatch,
  ListParams,
} from './schemas'

const detailKey = (kind: string, id: string) => ['application', kind, id] as const

export function useApplications(params: Omit<ListParams, 'cursor'>) {
  const source = useDataSource()
  return useInfiniteQuery({
    queryKey: ['applications', source.kind, 'list', params],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => source.listApplications({ ...params, cursor: pageParam }),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  })
}

export function useApplication(id: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: detailKey(source.kind, id),
    queryFn: () => source.getApplication(id),
  })
}

export function useEvents(id: string) {
  const source = useDataSource()
  return useQuery({
    queryKey: ['events', source.kind, id],
    queryFn: () => source.listEvents(id),
  })
}

export function applyPatch<T extends Application>(current: T, patch: ApplicationPatch): T {
  const next = { ...current, ...patch }
  if (patch.status) {
    next.display_status = patch.status
    next.status_locked = true
  }
  return next
}

type Pages = InfiniteData<ApplicationPage, string | undefined>

export function useUpdateApplication(id: string) {
  const source = useDataSource()
  const client = useQueryClient()
  const key = detailKey(source.kind, id)
  const listKey = ['applications', source.kind, 'list'] as const
  return useMutation({
    // Serialize edits per application so a failed earlier edit can't clobber a later one.
    scope: { id: `application-${id}` },
    mutationFn: (patch: ApplicationPatch) => source.updateApplication(id, patch),
    onMutate: async (patch) => {
      await client.cancelQueries({ queryKey: key })
      await client.cancelQueries({ queryKey: listKey })
      const previous = client.getQueryData<ApplicationDetail>(key)
      const previousLists = client.getQueriesData<Pages>({ queryKey: listKey })
      if (previous) client.setQueryData(key, applyPatch(previous, patch))
      client.setQueriesData<Pages>(
        { queryKey: listKey },
        (data) =>
          data && {
            ...data,
            pages: data.pages.map((page) => ({
              ...page,
              items: page.items.map((a) => (a.id === id ? applyPatch(a, patch) : a)),
            })),
          },
      )
      return { previous, previousLists }
    },
    onError: (_error, _patch, context) => {
      if (context?.previous) client.setQueryData(key, context.previous)
      context?.previousLists.forEach(([k, data]) => client.setQueryData(k, data))
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key })
      void client.invalidateQueries({ queryKey: ['applications', source.kind] })
      void client.invalidateQueries({ queryKey: ['events', source.kind, id] })
    },
  })
}
