import type { CounterAnswer, CounterPick, TeamMember } from '@/api/client'
import { useCounterTeam } from '@/api/queries'
import { cn } from '@/lib/utils'

import { DisplayName, EmptyState, ErrorState, MultiplierBadge, Sprite, TypeBadges } from './primitives'

/**
 * One pick's reasoning, as a small table.
 *
 * The reasoning is the differentiator, so it is rendered inline rather than
 * hidden behind a tooltip. Phase 9 adds move, turns-to-KO, and speed fields to
 * each answer; they become extra columns here without the shape changing.
 */
function AnswerTable({ answers }: { answers: CounterAnswer[] }) {
  return (
    <table className="w-full text-left text-[11px]">
      <thead className="text-muted-foreground">
        <tr>
          <th scope="col" className="font-normal">Against</th>
          <th scope="col" className="w-16 font-normal">Score</th>
          <th scope="col" className="hidden font-normal sm:table-cell">Why</th>
        </tr>
      </thead>
      <tbody>
        {[...answers]
          .sort((a, b) => b.multiplier - a.multiplier)
          .map((answer) => (
            <tr key={answer.enemy_id} className="border-border/50 border-t">
              <td className="py-1">
                <DisplayName name={answer.enemy_name} />
              </td>
              <td className="py-1">
                <MultiplierBadge value={answer.multiplier} />
              </td>
              <td className="text-muted-foreground hidden py-1 sm:table-cell">
                {answer.rationale}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  )
}

function PickCard({ pick }: { pick: CounterPick }) {
  const primary = pick.types[0]
  return (
    <li data-type={primary} className="card-surface relative flex flex-col gap-2 p-3">
      <span
        aria-hidden
        className="absolute inset-y-3 left-0 w-0.5 rounded-full"
        style={{ background: 'var(--type)' }}
      />
      <div className="flex items-center gap-3">
        <Sprite src={pick.sprite_url} alt={pick.name} size="sm" type={primary} />
        <div className="min-w-0">
          <DisplayName name={pick.name} className="font-display block truncate text-sm font-medium" />
          <TypeBadges types={pick.types} className="mt-1" />
        </div>
      </div>
      <AnswerTable answers={pick.answers} />
    </li>
  )
}

export function CounterTeam({ members }: { members: TeamMember[] }) {
  const counter = useCounterTeam()
  const ids = members.map((member) => member.pokemon_id)

  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-center gap-2">
        <h2 className="font-display mr-auto text-sm font-medium">Counter-team</h2>
        <button
          type="button"
          disabled={ids.length === 0 || counter.isPending}
          onClick={() => counter.mutate(ids)}
          className={cn(
            'border-border bg-card h-8 rounded-[8px] border px-3 text-xs font-medium',
            'hover:bg-muted disabled:opacity-40',
          )}
        >
          {counter.isPending ? 'Thinking…' : 'Build counter-team'}
        </button>
      </header>

      {counter.isError ? (
        <ErrorState message="Could not build a counter-team." onRetry={() => counter.mutate(ids)} />
      ) : counter.isPending ? (
        <ul className="flex flex-col gap-2">
          {Array.from({ length: 3 }, (_, index) => (
            <li key={index} className="card-surface h-28 p-3">
              <div className="bg-muted skeleton-shimmer relative h-full w-full overflow-hidden rounded" />
            </li>
          ))}
        </ul>
      ) : counter.data ? (
        <>
          <ul className="flex flex-col gap-2">
            {counter.data.picks.map((pick) => (
              <PickCard key={pick.id} pick={pick} />
            ))}
          </ul>
          <div className="card-surface p-3">
            <h3 className="text-muted-foreground mb-2 text-[11px] font-medium">Coverage</h3>
            <ul className="flex flex-col gap-1">
              {counter.data.coverage.map((entry) => (
                <li key={entry.enemy_id} className="flex items-center gap-2 text-[11px]">
                  <DisplayName name={entry.enemy_name} className="w-24 shrink-0 truncate" />
                  <span className="text-muted-foreground flex-1 truncate">
                    best answer <DisplayName name={entry.best_answer} className="text-foreground" />
                  </span>
                  <MultiplierBadge value={entry.score} />
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : (
        <EmptyState
          title={ids.length === 0 ? 'Add Pokémon to your team first' : 'No counter-team yet'}
          hint={
            ids.length === 0
              ? 'Drag from the catalog into a slot, then build a counter-team.'
              : 'Suggests six Pokémon that answer this team, with the reasoning for each.'
          }
        />
      )}
    </section>
  )
}
