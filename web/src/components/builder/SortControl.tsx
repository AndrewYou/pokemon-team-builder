import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

import type { SortField, SortOrder } from '@/api/queries'
import { cn } from '@/lib/utils'

/**
 * Sort field and direction, as two controls.
 *
 * The direction is separate rather than folded into the field list. Ten fields
 * would become twenty options, and twenty again with the next field added.
 */

interface SortFieldDef {
  value: SortField
  label: string
  group: string
  /** Ascending means something different per field, so each says so. */
  ascending: string
  descending: string
  /** Nobody sorts by Attack to find the weakest Pokemon. */
  defaultOrder: SortOrder
}

const ALPHA = { ascending: 'A to Z', descending: 'Z to A' } as const
const MAGNITUDE = { ascending: 'Weakest first', descending: 'Strongest first' } as const

export const SORT_FIELDS: SortFieldDef[] = [
  { value: 'id', label: 'Pokédex order', group: 'General', ascending: 'Lowest first', descending: 'Highest first', defaultOrder: 'asc' },
  { value: 'name', label: 'Name', group: 'General', ...ALPHA, defaultOrder: 'asc' },

  { value: 'stat_total', label: 'Total base stats', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_hp', label: 'HP', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_atk', label: 'Attack', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_def', label: 'Defense', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_spatk', label: 'Sp. Attack', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_spdef', label: 'Sp. Defense', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },
  { value: 'base_speed', label: 'Speed', group: 'Base stats', ...MAGNITUDE, defaultOrder: 'desc' },

  { value: 'type1', label: 'Type', group: 'Other', ...ALPHA, defaultOrder: 'asc' },
]

// Insertion order is the display order, so General comes before Base stats.
const GROUPS = [...new Set(SORT_FIELDS.map((field) => field.group))]

const CONTROL = 'border-border bg-card h-8 rounded-[8px] border text-xs'

export function SortControl({
  sort,
  order,
  onChange,
}: {
  sort: SortField
  order: SortOrder
  onChange: (sort: SortField, order: SortOrder) => void
}) {
  const field = SORT_FIELDS.find((candidate) => candidate.value === sort) ?? SORT_FIELDS[0]
  const directionLabel = order === 'asc' ? field.ascending : field.descending

  return (
    <div className="flex items-center gap-1">
      <div className={cn(CONTROL, 'relative flex items-center gap-1 pl-2')}>
        <ArrowUpDown aria-hidden className="text-muted-foreground size-3 shrink-0" />
        {/* Spelled out. A bare dropdown reading "Name" beside a search box
            looks like a filter, not an ordering. */}
        <span className="text-muted-foreground shrink-0">Sort:</span>
        <select
          value={sort}
          onChange={(event) => {
            const next = event.target.value as SortField
            const nextField = SORT_FIELDS.find((candidate) => candidate.value === next)
            // Switching field picks the direction people actually want rather
            // than carrying the previous one over.
            onChange(next, nextField?.defaultOrder ?? 'asc')
          }}
          aria-label="Sort field"
          className="h-full cursor-pointer bg-transparent pr-2 focus-visible:outline-none"
        >
          {/* Grouped with labels: ten flat options is a wall. optgroup gives
              the same grouping natively, keeps this consistent with the other
              controls here, and uses the platform picker on mobile. */}
          {GROUPS.map((group) => (
            <optgroup key={group} label={group}>
              {SORT_FIELDS.filter((option) => option.group === group).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      <button
        type="button"
        onClick={() => onChange(sort, order === 'asc' ? 'desc' : 'asc')}
        // The icon shows the current direction; the words say what that means
        // for this particular field.
        title={directionLabel}
        aria-label={`Sort direction: ${directionLabel}. Click to reverse.`}
        className={cn(CONTROL, 'hover:bg-muted grid w-8 place-items-center')}
      >
        {order === 'asc' ? (
          <ArrowUp aria-hidden className="size-3.5" />
        ) : (
          <ArrowDown aria-hidden className="size-3.5" />
        )}
      </button>
    </div>
  )
}
