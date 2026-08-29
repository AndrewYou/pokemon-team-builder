import { useEffect, useRef, useState } from 'react'

import type { TypeName } from '@/api/client'
import { useCatalog, type CatalogFilters } from '@/api/queries'
import { cn } from '@/lib/utils'

import { DraggablePokemonCard, PokemonCardSkeleton } from './PokemonCard'
import { EmptyState, ErrorState } from './primitives'

const TYPES: TypeName[] = [
  'normal', 'fire', 'water', 'electric', 'grass', 'ice',
  'fighting', 'poison', 'ground', 'flying', 'psychic', 'bug',
  'rock', 'ghost', 'dragon', 'dark', 'steel', 'fairy',
]

// repeat(auto-fill, minmax(180px, 1fr)) -- the column count follows the
// viewport rather than a breakpoint table.
const GRID = 'grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(180px,1fr))]'

export function Catalog({ rosterFull }: { rosterFull: boolean }) {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [type, setType] = useState<string>('')
  const [sort, setSort] = useState<CatalogFilters['sort']>('id')

  // Typing should not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])

  const query = useCatalog({ search: debounced, type, sort })
  const sentinel = useRef<HTMLDivElement>(null)

  // Infinite scroll via IntersectionObserver rather than a scroll listener:
  // no per-frame work, and it keeps working inside any scroll container.
  useEffect(() => {
    const node = sentinel.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && query.hasNextPage && !query.isFetchingNextPage) {
          void query.fetchNextPage()
        }
      },
      { rootMargin: '600px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [query])

  const items = query.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section className="flex min-h-0 flex-col gap-3">
      <header className="flex flex-wrap items-center gap-2">
        <h2 className="font-display mr-auto text-sm font-medium">Catalog</h2>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name"
          aria-label="Search Pokémon by name"
          className={cn(
            'border-border bg-card h-8 w-40 rounded-[8px] border px-2.5 text-xs',
            'focus-visible:ring-ring focus-visible:ring-1 focus-visible:outline-none',
          )}
        />
        <select
          value={type}
          onChange={(event) => setType(event.target.value)}
          aria-label="Filter by type"
          className="border-border bg-card h-8 rounded-[8px] border px-2 text-xs capitalize"
        >
          <option value="">All types</option>
          {TYPES.map((option) => (
            <option key={option} value={option} className="capitalize">
              {option}
            </option>
          ))}
        </select>
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as CatalogFilters['sort'])}
          aria-label="Sort order"
          className="border-border bg-card h-8 rounded-[8px] border px-2 text-xs"
        >
          <option value="id">Pokédex order</option>
          <option value="name">Name</option>
        </select>
      </header>

      {query.isError ? (
        <ErrorState message="The catalog could not be loaded." onRetry={() => void query.refetch()} />
      ) : query.isPending ? (
        // Skeletons matched to the real card dimensions, so nothing shifts
        // when the data lands.
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
          <div className={GRID}>
            {items.map((pokemon, index) => (
              <DraggablePokemonCard
                key={pokemon.id}
                pokemon={pokemon}
                index={index}
                disabled={rosterFull}
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
