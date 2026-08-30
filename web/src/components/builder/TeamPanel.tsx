import { Eraser, Shuffle } from 'lucide-react'
import { useState } from 'react'

import type { PokemonSummary, TeamMember, TeamRead } from '@/api/client'
import { useRandomTeam, type RosterEntry } from '@/api/queries'
import { cn } from '@/lib/utils'

import { CounterTeam } from './CounterTeam'
import { TeamHeader } from './TeamHeader'
import { MAX_SLOTS, TeamSlots } from './TeamSlots'
import { UndoToast } from './UndoToast'

function toEntry(source: TeamMember | PokemonSummary): RosterEntry {
  return {
    pokemon_id: 'pokemon_id' in source ? source.pokemon_id : source.id,
    name: source.name,
    sprite_url: source.sprite_url,
    types: source.types,
  }
}

const ACTION = cn(
  'text-muted-foreground hover:text-foreground hover:bg-muted flex h-7 items-center gap-1',
  'rounded-[6px] px-1.5 text-[11px] disabled:pointer-events-none disabled:opacity-40',
)

/**
 * Everything about the current team, in one column.
 *
 * Shared by the desktop sidebar and the sheet the tablet rail and mobile bar
 * open, so the three layouts cannot drift apart.
 */
export function TeamPanel({
  teams,
  team,
  members,
  activeType,
  onSelect,
  onRemove,
  onReplaceRoster,
}: {
  teams: TeamRead[]
  team: TeamRead | null
  members: TeamMember[]
  activeType?: string
  onSelect: (id: number | null) => void
  onRemove: (pokemonId: number) => void
  onReplaceRoster: (entries: RosterEntry[]) => void
}) {
  const randomTeam = useRandomTeam()
  // The roster as it was before the clear, so undo restores the exact order
  // rather than the same six Pokemon in whatever sequence comes back.
  const [undoTo, setUndoTo] = useState<RosterEntry[] | null>(null)
  const empty = members.length === 0

  function clear() {
    setUndoTo(members.map(toEntry))
    onReplaceRoster([])
  }

  function fillRandom() {
    randomTeam.mutate(MAX_SLOTS, {
      onSuccess: (picks) => onReplaceRoster(picks.map(toEntry)),
    })
  }

  return (
    <div className="flex flex-col gap-4 p-3">
      <div className="flex items-center gap-1">
        <div className="min-w-0 flex-1">
          <TeamHeader teams={teams} team={team} onSelect={onSelect} />
        </div>

        <button
          type="button"
          onClick={fillRandom}
          disabled={randomTeam.isPending}
          title="Fill the team with random Pokémon"
          aria-label="Fill the team with random Pokémon"
          className={ACTION}
        >
          <Shuffle aria-hidden className="size-3" />
          <span className="max-lg:hidden">Random</span>
        </button>

        {/* Hidden when there is nothing to clear: a clear button on an empty
            team is noise. Muted rather than red -- this is reversible, and red
            belongs on deleting the team itself. */}
        {empty ? null : (
          <button
            type="button"
            onClick={clear}
            title="Clear the team"
            aria-label="Clear the team"
            className={ACTION}
          >
            <Eraser aria-hidden className="size-3" />
            <span className="max-lg:hidden">Clear</span>
          </button>
        )}

        <span className="text-muted-foreground tabular shrink-0 pl-1 text-xs">
          {members.length}/{MAX_SLOTS}
        </span>
      </div>

      <TeamSlots members={members} activeType={activeType} onRemove={onRemove} />

      <CounterTeam members={members} />

      {undoTo ? (
        <UndoToast
          message="Team cleared"
          onUndo={() => {
            onReplaceRoster(undoTo)
            setUndoTo(null)
          }}
          onDismiss={() => setUndoTo(null)}
        />
      ) : null}
    </div>
  )
}
