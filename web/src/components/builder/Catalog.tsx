import { useEffect, useRef, useState, type RefObject } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { PokemonSummary, TypeName } from '@/api/client'
import { useCatalog, type SortField, type SortOrder } from '@/api/queries'
import { cn } from '@/lib/utils'

import { CatalogCard, PokemonCardSkeleton } from './PokemonCard'
import { EmptyState, ErrorState } from './primitives'
import { SORT_FIELDS, SortControl } from './SortControl'

const TYPES: TypeName[] = [
  'normal', 'fire', 'water', 'electric', 'grass', 'ice',
  'fighting', 'poison', 'ground', 'flying', 'psychic', 'bug',
  'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy',
]

const GRID = 'grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(180px,1fr))]'
const CONTROL = 'border-border bg-card h-8 rounded-[8px] border px-2 text-xs'

export function Catalog({
  teamIds,
  rosterFull,
  onAdd,
  scrollRef,
}: {
  teamIds: number[]
  rosterFull: boolean
  onAdd: (pokemon: PokemonSummary) => void
  scrollRef: RefObject<HTMLDivElement | null>
}) {
  // Sort lives in the URL, so a sorted view survives a reload and can be
  // shared as a link.
  const [params, setParams] = useSearchParams()
  const sort = (params.get('sort') as SortField) ?? 'id'
  const order = (params.get('order') as SortOrder) ?? 'asc'

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [type, setType] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])

  function changeSort(nextSort: SortField, nextOrder: SortOrder) {
    const next = new URLSearchParams(params)
    next.set('sort', nextSort)
    next.set('order', nextOrder)
    setParams(next, { replace: true })
    // Pagination resets on its own -- the query key changed -- but the grid
    // stays where it was scrolled, which would show page one from the middle.
    scrollRef.current?.scrollTo({ top: 0 })
  }

  const query = useCatalog({ search: debounced, type, sort, order })
  const sentinel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = sentinel.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && query.hasNextPage && !query.isFetchingNextPage) {
          void query.fetchNextPage()
        }
      },
      // The grid is its own scroll container, so the observer has to watch
      // that rather than the viewport.
      { root: scrollRef.current, rootMargin: '600px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [query, scrollRef])

  const items = query.data?.pages.flatMap((page) => page.items) ?? []
  const inTeam = new Set(teamIds)
  const fieldLabel = SORT_FIELDS.find((f) => f.value === sort)?.label ?? 'Pokédex order'

  return (
    <section className="flex flex-col gap-3 p-3">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="font-display mr-auto text-sm font-medium">Catalog</h2>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name"
          aria-label="Search Pokémon by name"
          className={cn(CONTROL, 'w-36 focus-visible:ring-ring focus-visible:ring-1 focus-visible:outline-none')}
        />
        <select
          value={type}
          onChange={(event) => {
            setType(event.target.value)
            scrollRef.current?.scrollTo({ top: 0 })
          }}
          aria-label="Filter by type"
          className={cn(CONTROL, 'capitalize')}
        >
          <option value="">All types</option>
          {TYPES.map((option) => (
            <option key={option} value={option} className="capitalize">
              {option}
            </option>
          ))}
        </select>
        <SortControl sort={sort} order={order} onChange={changeSort} />
      </header>

      {query.isError ? (
        <ErrorState message="The catalog could not be loaded." onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        <div className={GRID}>
          {Array.from({ length: 12 }, (_, index) => (
            <PokemonCardSkeleton key={index} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          title="Nothing matches those filters"
          hint="Try a shorter search, or clear the type filter."
        />
      ) : (
        <>
          <p className="sr-only" aria-live="polite">
            Sorted by {fieldLabel}, {order === 'asc' ? 'ascending' : 'descending'}
          </p>
          <div className={GRID}>
            {items.map((pokemon, index) => (
              <CatalogCard
                key={pokemon.id}
                pokemon={pokemon}
                index={index}
                inTeam={inTeam.has(pokemon.id)}
                rosterFull={rosterFull}
                onAdd={onAdd}
              />
            ))}
          </div>
          <div ref={sentinel} aria-hidden className="h-px" />
          {query.isFetchingNextPage ? (
            <div className={GRID}>
              {Array.from({ length: 6 }, (_, index) => (
                <PokemonCardSkeleton key={index} />
              ))}
            </div>
          ) : null}
          {!query.hasNextPage ? (
            <p className="text-muted-foreground py-4 text-center text-xs">
              {items.length} Pokémon — that’s all of them.
            </p>
          ) : null}
        </>
      )}
    </section>
  )
}
