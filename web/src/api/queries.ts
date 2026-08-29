/**
 * Server state. Every read and write goes through TanStack Query so caching,
 * refetching, and optimistic updates are handled in one place.
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { api, type PokemonPage, type TeamRead } from './client'

export const keys = {
  catalog: (filters: CatalogFilters) => ['catalog', filters] as const,
  teams: ['teams'] as const,
  alerts: ['alerts'] as const,
  counterTeam: ['counter-team'] as const,
}

export interface CatalogFilters {
  search?: string
  type?: string
  sort?: 'id' | 'name'
}

const PAGE_SIZE = 48

export function useCatalog(filters: CatalogFilters) {
  return useInfiniteQuery({
    queryKey: keys.catalog(filters),
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const { data, error } = await api.GET('/pokemon', {
        params: {
          query: {
            cursor: pageParam,
            limit: PAGE_SIZE,
            search: filters.search || undefined,
            // The generated union is the 18 canonical types; an empty filter
            // has to be absent rather than an empty string.
            type: (filters.type || undefined) as never,
            sort: filters.sort ?? 'id',
          },
        },
        signal,
      })
      if (error) throw new Error('Could not load the catalog')
      return data as PokemonPage
    },
    // Cursor pagination: the server decides where the next page starts, and
    // null means there is no next page.
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    staleTime: 5 * 60_000,
  })
}

export function useTeams() {
  return useQuery({
    queryKey: keys.teams,
    queryFn: async () => {
      const { data, error } = await api.GET('/teams')
      if (error) throw new Error('Could not load your teams')
      return data as TeamRead[]
    },
  })
}

export function useCreateTeam() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error } = await api.POST('/teams', { body: { name } })
      if (error) throw new Error('Could not create the team')
      return data as TeamRead
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.teams }),
  })
}

export function useRenameTeam() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) => {
      const { data, error } = await api.PATCH('/teams/{team_id}', {
        params: { path: { team_id: id } },
        body: { name },
      })
      if (error) throw new Error('Could not rename the team')
      return data as TeamRead
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.teams }),
  })
}

export function useDeleteTeam() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (id: number) => {
      const { error } = await api.DELETE('/teams/{team_id}', {
        params: { path: { team_id: id } },
      })
      if (error) throw new Error('Could not delete the team')
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.teams }),
  })
}

/**
 * Replace a team's whole roster.
 *
 * Optimistic: a drag should land where it was dropped, not snap back and then
 * jump into place when the server answers. The previous roster is kept so a
 * failure can restore it.
 */
export function useSetRoster() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, pokemonIds }: { id: number; pokemonIds: number[] }) => {
      const { data, error } = await api.PUT('/teams/{team_id}/members', {
        params: { path: { team_id: id } },
        body: { pokemon_ids: pokemonIds },
      })
      if (error) throw new Error('Could not save the roster')
      return data as TeamRead
    },
    onMutate: async ({ id, pokemonIds }) => {
      await client.cancelQueries({ queryKey: keys.teams })
      const previous = client.getQueryData<TeamRead[]>(keys.teams)
      client.setQueryData<TeamRead[]>(keys.teams, (teams) =>
        teams?.map((team) =>
          team.id === id
            ? {
                ...team,
                members: pokemonIds.map((pokemonId, index) => {
                  const existing = team.members.find((m) => m.pokemon_id === pokemonId)
                  return (
                    existing
                      ? { ...existing, slot: index + 1 }
                      : {
                          slot: index + 1,
                          pokemon_id: pokemonId,
                          name: '',
                          sprite_url: null,
                          types: [],
                        }
                  ) as TeamRead['members'][number]
                }),
              }
            : team,
        ),
      )
      return { previous }
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) client.setQueryData(keys.teams, context.previous)
    },
    onSettled: () => {
      client.invalidateQueries({ queryKey: keys.teams })
      client.invalidateQueries({ queryKey: keys.counterTeam })
    },
  })
}

export function useAlerts() {
  return useQuery({
    queryKey: keys.alerts,
    queryFn: async () => {
      const { data, error } = await api.GET('/alerts')
      if (error) throw new Error('Could not load alerts')
      return data
    },
  })
}

export function useDismissAlert() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: async (changeId: number) => {
      const { error } = await api.POST('/alerts/{change_id}/dismiss', {
        params: { path: { change_id: changeId } },
      })
      if (error) throw new Error('Could not dismiss the alert')
    },
    onSuccess: () => client.invalidateQueries({ queryKey: keys.alerts }),
  })
}

export function useCounterTeam() {
  return useMutation({
    mutationKey: keys.counterTeam,
    mutationFn: async (pokemonIds: number[]) => {
      const { data, error } = await api.POST('/counter-team', {
        body: { pokemon_ids: pokemonIds },
      })
      if (error) throw new Error('Could not build a counter-team')
      return data
    },
  })
}
