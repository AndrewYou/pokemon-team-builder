import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

import type { SortField, SortOrder } from '@/api/queries'
import { cn } from '@/lib/utils'

/**
 * Sort field and direction, as two controls.
 *
 * The direction is separate rather than folded into the field list. Doubling
 * every option ("Name A-Z", "Name Z-A", ...) makes the menu twice as long and
 * doubles again with each field added.
 */

export const SORT_FIELDS: {
  value: SortField
  label: string
  /** Ascending means something different per field, so each says so. */
  ascending: string
  descending: string
  /** Nobody sorts by Attack to find the weakest Pokemon. */
  defaultOrder: SortOrder
}[] = [
  { value: 'id', label: 'Pokédex order', ascending: 'Lowest first', descending: 'Highest first', defaultOrder: 'asc' },
  { value: 'name', label: 'Name', ascending: 'A to Z', descending: 'Z to A', defaultOrder: 'asc' },
  { value: 'total', label: 'Total base stats', ascending: 'Weakest first', descending: 'Strongest first', defaultOrder: 'desc' },
  { value: 'hp', label: 'HP', ascending: 'Weakest first', descending: 'Strongest first', defaultOrder: 'desc' },
  { value: 'attack', label: 'Attack', ascending: 'Weakest first', descending: 'Strongest first', defaultOrder: 'desc' },
  { value: 'speed', label: 'Speed', ascending: 'Slowest first', descending: 'Fastest first', defaultOrder: 'desc' },
]

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
        {/* "Sort:" spelled out. A bare dropdown reading "Name" beside a search
            box looks like a filter, not an ordering. */}
        <span className="text-muted-foreground shrink-0">Sort:</span>
        <select
          value={sort}
          onChange={(event) => {
            const next = event.target.value as SortField
            const nextField = SORT_FIELDS.find((candidate) => candidate.value === next)
            onChange(next, nextField?.defaultOrder ?? 'asc')
          }}
          aria-label="Sort field"
          className="h-full cursor-pointer bg-transparent pr-2 focus-visible:outline-none"
        >
          {SORT_FIELDS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
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
