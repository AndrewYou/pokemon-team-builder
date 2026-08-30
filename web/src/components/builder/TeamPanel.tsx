import type { TeamMember, TeamRead } from '@/api/client'

import { CounterTeam } from './CounterTeam'
import { TeamHeader } from './TeamHeader'
import { MAX_SLOTS, TeamSlots } from './TeamSlots'

/**
 * Everything about the current team, in one column.
 *
 * Shared by the desktop sidebar and the sheet that the tablet rail and mobile
 * bar open, so the three layouts cannot drift apart.
 */
export function TeamPanel({
  teams,
  team,
  members,
  activeType,
  onSelect,
  onRemove,
}: {
  teams: TeamRead[]
  team: TeamRead | null
  members: TeamMember[]
  activeType?: string
  onSelect: (id: number | null) => void
  onRemove: (pokemonId: number) => void
}) {
  return (
    <div className="flex flex-col gap-4 p-3">
      <div className="flex items-center justify-between gap-2">
        <TeamHeader teams={teams} team={team} onSelect={onSelect} />
        <span className="text-muted-foreground tabular shrink-0 text-xs">
          {members.length}/{MAX_SLOTS}
        </span>
      </div>

      <TeamSlots members={members} activeType={activeType} onRemove={onRemove} />

      <CounterTeam members={members} />
    </div>
  )
}
