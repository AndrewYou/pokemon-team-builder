import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'

import type { PokemonSummary } from '@/api/client'
import { cn } from '@/lib/utils'

import { DisplayName, Sprite, TypeBadges } from './primitives'

const STAT_LABELS: Record<string, string> = {
  hp: 'HP',
  attack: 'ATK',
  defense: 'DEF',
  special_attack: 'SPA',
  special_defense: 'SPD',
  speed: 'SPE',
}

export function CardBody({ pokemon, dragging }: { pokemon: PokemonSummary; dragging?: boolean }) {
  const primary = pokemon.types[0]
  return (
    <div
      data-type={primary}
      className={cn(
        'card-surface relative flex h-full flex-col gap-2 p-3 text-left',
        'transition-[border-color] duration-150',
        dragging && 'shadow-2xl',
      )}
    >
      <span
        aria-hidden
        className="absolute inset-x-3 top-0 h-px rounded-full"
        style={{ background: 'var(--type)' }}
      />
      <Sprite src={pokemon.sprite_url} alt={pokemon.name} type={primary} />
      <div className="flex items-baseline justify-between gap-2">
        <DisplayName name={pokemon.name} className="font-display truncate text-sm font-medium" />
        <span className="text-muted-foreground tabular text-[11px]">
          #{String(pokemon.id).padStart(3, '0')}
        </span>
      </div>
      <TypeBadges types={pokemon.types} />
      <dl className="text-muted-foreground mt-auto grid grid-cols-3 gap-x-2 gap-y-0.5 text-[10px]">
        {Object.entries(STAT_LABELS).map(([key, label]) => (
          <div key={key} className="flex justify-between gap-1">
            <dt>{label}</dt>
            <dd className="tabular text-foreground/80">
              {pokemon.stats[key as keyof typeof pokemon.stats]}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/**
 * A catalog card.
 *
 * Adding is a click, not a drag. Dragging a card across a long scrolling grid
 * into a panel is fiddly with a mouse and needs long-press gymnastics on
 * touch, so the primary path is a button and the drag is an enhancement.
 *
 * The drag listeners sit on the wrapper while the add control is a real
 * nested button. They cannot be the same element: dnd-kit's keyboard sensor
 * lifts with Space, which is also what activates a button, so a single
 * element would both add and start a drag on one keypress.
 */
export function CatalogCard({
  pokemon,
  index,
  inTeam,
  rosterFull,
  onAdd,
}: {
  pokemon: PokemonSummary
  index: number
  inTeam: boolean
  rosterFull: boolean
  onAdd: (pokemon: PokemonSummary) => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `catalog-${pokemon.id}`,
    data: { pokemon },
    disabled: inTeam || rosterFull,
  })

  const disabled = inTeam || rosterFull
  const label = inTeam
    ? `${pokemon.name} is already on your team`
    : rosterFull
      ? 'Your team is full'
      : `Add ${pokemon.name} to your team`

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      // `attributes` is deliberately not spread: it would make this div a
      // focusable role="button", nesting an interactive control inside another.
      aria-roledescription={attributes['aria-roledescription']}
      style={{
        transform: CSS.Translate.toString(transform),
        animationDelay: `${Math.min(index, 12) * 18}ms`,
      }}
      className={cn(
        'card-enter group relative touch-none rounded-[12px]',
        !disabled && 'cursor-grab active:cursor-grabbing',
        isDragging && 'opacity-40',
      )}
    >
      <CardBody pokemon={pokemon} />

      <button
        type="button"
        disabled={disabled}
        onClick={() => onAdd(pokemon)}
        // Without this the card's drag listener claims the press and the
        // button never sees the click.
        onPointerDown={(event) => event.stopPropagation()}
        aria-label={label}
        title={label}
        className={cn(
          'absolute top-2 right-2 grid size-7 place-items-center rounded-full text-sm',
          'border-border bg-card/90 border backdrop-blur transition-opacity duration-150',
          'focus-visible:ring-ring focus-visible:opacity-100 focus-visible:ring-2 focus-visible:outline-none',
          // Hover reveals it on a pointer device. Below md it is always
          // visible: there is no hover on a phone, and hover-capability media
          // queries are not reliable enough to be the only thing standing
          // between a touch user and the primary way to add a Pokemon.
          'opacity-0 group-hover:opacity-100 max-md:opacity-100 [@media(hover:none)]:opacity-100',
          disabled
            ? 'text-muted-foreground cursor-not-allowed opacity-100'
            : 'hover:border-[color-mix(in_oklch,var(--type)_60%,var(--border))] hover:text-[var(--type)]',
        )}
        data-type={pokemon.types[0]}
      >
        {inTeam ? '✓' : '+'}
      </button>
    </div>
  )
}

export function PokemonCardSkeleton() {
  return (
    <div className="card-surface flex h-full flex-col gap-2 p-3">
      <div className="bg-muted skeleton-shimmer relative h-32 w-full overflow-hidden rounded-[10px]" />
      <div className="bg-muted skeleton-shimmer relative h-4 w-2/3 overflow-hidden rounded" />
      <div className="bg-muted skeleton-shimmer relative h-4 w-1/2 overflow-hidden rounded" />
      <div className="bg-muted skeleton-shimmer relative mt-auto h-8 w-full overflow-hidden rounded" />
    </div>
  )
}
