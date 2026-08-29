import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

import type { TeamMember } from '@/api/client'
import { cn } from '@/lib/utils'

import { DisplayName, Sprite, TypeBadges } from './primitives'

export const MAX_SLOTS = 6

/**
 * Filled: a solid card, tinted with the occupant's type.
 *
 * Deliberately a different visual language from an empty slot. When both read
 * as "something is missing", the moment a Pokemon lands is ambiguous.
 */
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
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        background: 'color-mix(in oklch, var(--type) 7%, var(--card))',
      }}
      className={cn(
        'border-border relative flex h-[60px] items-center gap-2.5 rounded-[12px] border px-2',
        isDragging && 'z-10 opacity-40',
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-2 left-0 w-0.5 rounded-full"
        style={{ background: 'var(--type)' }}
      />
      <span className="text-muted-foreground tabular w-3 shrink-0 text-center text-[11px]">
        {index + 1}
      </span>
      {/* The drag handle is the sprite, and it is a real button so keyboard
          users can lift it. Reordering is where dragging genuinely beats
          clicking, and it is where "order matters" lives. */}
      <button
        type="button"
        {...listeners}
        {...attributes}
        aria-label={`${member.name}, slot ${index + 1}. Press space to reorder.`}
        className="focus-visible:ring-ring shrink-0 cursor-grab rounded-[10px] focus-visible:ring-2 focus-visible:outline-none active:cursor-grabbing"
      >
        <Sprite src={member.sprite_url} alt={member.name} size="sm" type={primary} />
      </button>
      <div className="min-w-0 flex-1">
        <DisplayName name={member.name} className="font-display block truncate text-xs font-medium" />
        <TypeBadges types={member.types} className="mt-0.5" />
      </div>
      <button
        type="button"
        onClick={() => onRemove(member.pokemon_id)}
        aria-label={`Remove ${member.name}`}
        className="text-muted-foreground hover:text-foreground hover:bg-muted grid size-6 shrink-0 place-items-center rounded-[6px] text-base leading-none"
      >
        ×
      </button>
    </li>
  )
}

/**
 * Pending: the filled shape with a shimmer where the sprite goes.
 *
 * Same dimensions as a filled slot, so resolving does not move anything. Only
 * reachable if a roster entry arrives without its display fields.
 */
function PendingSlot({ index }: { index: number }) {
  return (
    <li className="card-surface flex h-[60px] items-center gap-2.5 px-2">
      <span className="text-muted-foreground tabular w-3 shrink-0 text-center text-[11px]">
        {index + 1}
      </span>
      <div className="bg-muted skeleton-shimmer relative size-12 shrink-0 overflow-hidden rounded-[10px]" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="bg-muted skeleton-shimmer relative h-3 w-24 overflow-hidden rounded" />
        <div className="bg-muted skeleton-shimmer relative h-3 w-14 overflow-hidden rounded" />
      </div>
    </li>
  )
}

/** Empty: a dashed ghost. No label text -- the dashes and the number say it. */
function EmptySlot({ index, activeType }: { index: number; activeType?: string }) {
  const { setNodeRef, isOver } = useDroppable({ id: `slot-${index}` })
  return (
    <li
      ref={setNodeRef}
      data-type={activeType}
      aria-label={`Empty slot ${index + 1}`}
      className={cn(
        'border-border/50 text-muted-foreground/70 flex h-[60px] items-center gap-2.5 rounded-[12px]',
        'border border-dashed px-2 transition-all duration-150',
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
      <span className="tabular w-3 shrink-0 text-center text-[11px]">{index + 1}</span>
      <span className="border-border/50 size-12 shrink-0 rounded-[10px] border border-dashed" />
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
      <ul className="flex flex-col gap-1.5">
        {members.map((member, index) =>
          // A member without display fields cannot be drawn as filled; the
          // pending shape is the honest thing to show.
          member.name ? (
            <FilledSlot
              key={member.pokemon_id}
              member={member}
              index={index}
              onRemove={onRemove}
            />
          ) : (
            <PendingSlot key={member.pokemon_id} index={index} />
          ),
        )}
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

/** The compact strip used by the tablet rail and the mobile bar. */
export function SlotStrip({
  members,
  orientation = 'horizontal',
}: {
  members: TeamMember[]
  orientation?: 'horizontal' | 'vertical'
}) {
  const empties = Math.max(0, MAX_SLOTS - members.length)
  return (
    <div className={cn('flex gap-1.5', orientation === 'vertical' && 'flex-col')}>
      {members.map((member) => (
        <Sprite
          key={member.pokemon_id}
          src={member.sprite_url}
          alt={member.name}
          size="sm"
          type={member.types[0]}
        />
      ))}
      {Array.from({ length: empties }, (_, offset) => (
        <span
          key={offset}
          className="border-border/50 size-12 shrink-0 rounded-[10px] border border-dashed"
        />
      ))}
    </div>
  )
}
