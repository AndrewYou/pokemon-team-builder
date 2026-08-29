import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import type { TeamMember } from '@/api/client'
import { cn } from '@/lib/utils'

import { DisplayName, Sprite, TypeBadges } from './primitives'

export const MAX_SLOTS = 6

/** A filled slot. Sortable, so the roster can be reordered by dragging. */
function FilledSlot({
  member,
  index,
  onRemove,
}: {
  member: TeamMember
  index: number
  onRemove: (pokemonId: number) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `member-${member.pokemon_id}`,
    data: { member },
  })
  const primary = member.types[0]

  return (
    <li
      ref={setNodeRef}
      data-type={primary}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={cn(
        'card-surface relative flex items-center gap-3 p-2',
        'transition-[border-color] duration-150',
        isDragging && 'z-10 opacity-40',
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-2 left-0 w-0.5 rounded-full"
        style={{ background: 'var(--type)' }}
      />
      <span className="text-muted-foreground tabular w-4 shrink-0 text-center text-[11px]">
        {index + 1}
      </span>
      <button
        type="button"
        {...listeners}
        {...attributes}
        aria-label={`${member.name}, slot ${index + 1}. Press space to reorder.`}
        className="focus-visible:ring-ring cursor-grab rounded-[8px] focus-visible:ring-2 focus-visible:outline-none active:cursor-grabbing"
      >
        <Sprite src={member.sprite_url} alt={member.name} size="sm" type={primary} />
      </button>
      <div className="min-w-0 flex-1">
        <DisplayName name={member.name} className="font-display block truncate text-sm" />
        <TypeBadges types={member.types} className="mt-1" />
      </div>
      <button
        type="button"
        onClick={() => onRemove(member.pokemon_id)}
        aria-label={`Remove ${member.name} from the team`}
        className="text-muted-foreground hover:text-foreground hover:bg-muted grid size-7 shrink-0 place-items-center rounded-[8px] text-lg leading-none"
      >
        ×
      </button>
    </li>
  )
}

/**
 * An empty slot.
 *
 * All six are always rendered. An empty team then reads as "six slots to
 * fill" rather than as a blank area with nothing to act on.
 */
function EmptySlot({ index, activeType }: { index: number; activeType?: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${index}` })
  return (
    <li
      ref={setNodeRef}
      data-type={activeType}
      className={cn(
        'border-border/60 text-muted-foreground flex h-[60px] items-center gap-3 rounded-[12px]',
        'border border-dashed px-3 text-xs transition-all duration-150',
        // The drop target picks up the dragged Pokémon's own colour, so the
        // feedback says *what* is landing, not just that something is.
        isOver && 'border-solid',
      )}
      style={
        isOver
          ? {
              outline: '2px solid var(--type)',
              outlineOffset: '-2px',
              background: 'color-mix(in oklch, var(--type) 8%, transparent)',
            }
          : undefined
      }
    >
      <span className="tabular w-4 text-center text-[11px]">{index + 1}</span>
      <span>{isOver ? 'Drop to add' : 'Empty slot'}</span>
    </li>
  )
}

export function TeamSlots({
  members,
  activeType,
  onRemove,
}: {
  members: TeamMember[]
  activeType?: string
  onRemove: (pokemonId: number) => void
}) {
  const empties = Math.max(0, MAX_SLOTS - members.length)
  return (
    <SortableContext
      items={members.map((member) => `member-${member.pokemon_id}`)}
      strategy={verticalListSortingStrategy}
    >
      <ul className="flex flex-col gap-2">
        {members.map((member, index) => (
          <FilledSlot
            key={member.pokemon_id}
            member={member}
            index={index}
            onRemove={onRemove}
          />
        ))}
        {Array.from({ length: empties }, (_, offset) => (
          <EmptySlot
            key={`empty-${members.length + offset}`}
            index={members.length + offset}
            activeType={activeType}
          />
        ))}
      </ul>
    </SortableContext>
  )
}
