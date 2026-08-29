import type { TeamMember } from '@/api/client'
import { cn } from '@/lib/utils'

import { MAX_SLOTS, SlotStrip } from './TeamSlots'

/**
 * Tablet: a narrow rail of six sprites down the right edge, tapped to expand.
 *
 * At this width a full panel would eat the grid, but the roster still has to
 * stay on screen -- scrolling away to check what is already picked is the
 * problem being solved.
 */
export function TeamRail({
  members,
  onExpand,
}: {
  members: TeamMember[]
  onExpand: () => void
}) {
  return (
    <button
      type="button"
      onClick={onExpand}
      aria-label={`Open team panel. ${members.length} of ${MAX_SLOTS} slots filled.`}
      className={cn(
        'border-border bg-card/80 hidden shrink-0 flex-col items-center gap-2 border-l p-2',
        'backdrop-blur md:flex lg:hidden',
      )}
    >
      <span className="text-muted-foreground tabular text-[10px]">
        {members.length}/{MAX_SLOTS}
      </span>
      <SlotStrip members={members} orientation="vertical" />
    </button>
  )
}

/**
 * Mobile: a bar pinned above the grid, always visible.
 *
 * Six small slots and a fill count, expanding into the sheet for reordering
 * and team actions.
 */
export function TeamBar({
  members,
  onExpand,
}: {
  members: TeamMember[]
  onExpand: () => void
}) {
  return (
    <div
      className="border-border bg-background/95 z-30 border-t backdrop-blur md:hidden"
      style={{ paddingBottom: 'max(env(safe-area-inset-bottom), 8px)' }}
    >
      <button
        type="button"
        onClick={onExpand}
        aria-label={`Open team panel. ${members.length} of ${MAX_SLOTS} slots filled.`}
        className="flex w-full items-center gap-2 px-3 pt-2"
      >
        <span className="text-muted-foreground tabular shrink-0 text-[11px]">
          {members.length}/{MAX_SLOTS}
        </span>
        <div className="min-w-0 flex-1 overflow-x-auto">
          <SlotStrip members={members} />
        </div>
        <span aria-hidden className="text-muted-foreground shrink-0 text-[10px]">
          ▴
        </span>
      </button>
    </div>
  )
}
