import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useDataSource } from './context'
import type {
  Application,
  ApplicationDetail,
  ApplicationPage,
  ApplicationPatch,
  FollowUp,
  FollowUpFilter,
  SequencePatch,
  Tone,
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
      void client.invalidateQueries({
        queryKey: ['applications', source.kind],
      })
      void client.invalidateQueries({ queryKey: ['events', source.kind, id] })
    },
  })
}

export function useFollowUps(state: FollowUpFilter = 'all') {
  const source = useDataSource()
  return useQuery({
    queryKey: ['followups', source.kind, 'list', state],
    queryFn: () => source.listFollowUps(state),
  })
}

type FollowUpAction = 'skip' | 'delay'

function applyFollowUp(items: FollowUp[], id: string, action: FollowUpAction, days: number) {
  if (action === 'skip') return items.filter((t) => t.id !== id)
  return items
    .map((t) =>
      t.id === id
        ? {
            ...t,
            due_at: new Date(Date.parse(t.due_at) + days * 86_400_000).toISOString(),
          }
        : t,
    )
    .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at))
}

export function useFollowUpAction(id: string, action: FollowUpAction, days = 0) {
  const source = useDataSource()
  const client = useQueryClient()
  const listKey = ['followups', source.kind, 'list'] as const
  return useMutation({
    scope: { id: `followup-${id}` },
    mutationFn: () =>
      action === 'skip' ? source.skipFollowUp(id) : source.delayFollowUp(id, days),
    onMutate: async () => {
      await client.cancelQueries({ queryKey: listKey })
      const previous = client.getQueriesData<FollowUp[]>({ queryKey: listKey })
      client.setQueriesData<FollowUp[]>(
        { queryKey: listKey },
        (items) => items && applyFollowUp(items, id, action, days),
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      context?.previous.forEach(([k, data]) => client.setQueryData(k, data))
    },
    onSettled: () => void client.invalidateQueries({ queryKey: listKey }),
  })
}

export function useSequences() {
  const source = useDataSource()
  return useQuery({
    queryKey: ['sequences', source.kind],
    queryFn: () => source.listSequences(),
  })
}

export function useUpdateSequence(id: string) {
  const source = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (patch: SequencePatch) => source.updateSequence(id, patch),
    onSuccess: () => client.invalidateQueries({ queryKey: ['sequences', source.kind] }),
  })
}

export function useDisconnectGmail() {
  const source = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => source.disconnectGmail(),
    onSuccess: () => client.invalidateQueries({ queryKey: ['applications', source.kind] }),
  })
}

export function useDeleteAccount() {
  const source = useDataSource()
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => source.deleteAccount(),
    onSuccess: () => client.clear(),
  })
}

export function useDebounced<T>(value: T, ms = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

export function usePreview(template: string, tone: Tone) {
  const source = useDataSource()
  const debounced = useDebounced({ template, tone })
  return useQuery({
    queryKey: ['preview', source.kind, debounced.template, debounced.tone],
    queryFn: () => source.previewTemplate(debounced.template, debounced.tone),
    retry: false,
  })
}
