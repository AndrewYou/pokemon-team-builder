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
        'card-surface group relative flex h-full flex-col gap-2 p-3 text-left',
        'transition-[border-color,transform] duration-150',
        // A hairline that picks up the type colour on hover, rather than a
        // drop shadow. Elevation is reserved for the dragged card.
        'hover:border-[color-mix(in_oklch,var(--type)_45%,var(--border))]',
        dragging && 'shadow-2xl',
      )}
    >
      {/* A top hairline in the type colour: enough to scan by, far short of a
          type-coloured surface. */}
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
 * A catalog card that can be dragged into a team slot.
 *
 * Keyboard drag is enabled at the DndContext level, so the button needs to be
 * genuinely focusable -- this is a button, not a div with handlers.
 */
export function DraggablePokemonCard({
  pokemon,
  index,
  disabled,
}: {
  pokemon: PokemonSummary
  index: number
  disabled?: boolean
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `catalog-${pokemon.id}`,
    data: { pokemon },
    disabled,
  })

  return (
    <button
      ref={setNodeRef}
      type="button"
      {...listeners}
      {...attributes}
      aria-label={`${pokemon.name}, ${pokemon.types.join(' and ')} type. Press space to pick up.`}
      style={{
        transform: CSS.Translate.toString(transform),
        // A short stagger so the grid assembles rather than blinking in.
        animationDelay: `${Math.min(index, 12) * 18}ms`,
      }}
      className={cn(
        'card-enter cursor-grab touch-none focus-visible:outline-none',
        'focus-visible:ring-ring rounded-[12px] focus-visible:ring-2 focus-visible:ring-offset-2',
        'focus-visible:ring-offset-background active:cursor-grabbing',
        isDragging && 'opacity-40',
      )}
    >
      <CardBody pokemon={pokemon} />
    </button>
  )
}

export function PokemonCardSkeleton() {
  return (
    <div className="card-surface flex h-full flex-col gap-2 p-3">
      <div className="bg-muted skeleton-shimmer relative aspect-square w-full overflow-hidden rounded-[10px]" />
      <div className="bg-muted skeleton-shimmer relative h-4 w-2/3 overflow-hidden rounded" />
      <div className="bg-muted skeleton-shimmer relative h-4 w-1/2 overflow-hidden rounded" />
      <div className="bg-muted skeleton-shimmer relative mt-auto h-8 w-full overflow-hidden rounded" />
    </div>
  )
}
