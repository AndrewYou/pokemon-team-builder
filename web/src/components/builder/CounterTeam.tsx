import { useEffect, useRef, useState } from 'react'

import type { CounterAnswer, CounterPick, TeamMember } from '@/api/client'
import { useCounterTeam } from '@/api/queries'
import { cn } from '@/lib/utils'

import { DisplayName, EmptyState, ErrorState, MultiplierBadge, Sprite, TypeBadges } from './primitives'

/**
 * One pick's reasoning, as a small table.
 *
 * The reasoning is the differentiator, so it is inline rather than behind a
 * tooltip. A later damage model adds move, turns-to-KO and speed fields to each
 * answer; they become extra columns without the shape changing.
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
              <td className="py-1"><DisplayName name={answer.enemy_name} /></td>
              <td className="py-1"><MultiplierBadge value={answer.multiplier} /></td>
              <td className="text-muted-foreground hidden py-1 sm:table-cell">{answer.rationale}</td>
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
  const empty = ids.length === 0

  // A result describes the roster it was generated for. Once that roster
  // changes the picks are answering a team that no longer exists, so they are
  // dimmed rather than silently presented as current.
  const [generatedFor, setGeneratedFor] = useState<string | null>(null)
  const [showStale, setShowStale] = useState(false)
  const signature = ids.join(',')
  const stale = counter.data != null && generatedFor !== null && generatedFor !== signature
  const staleSize = generatedFor ? generatedFor.split(',').filter(Boolean).length : 0

  // A team emptied entirely has nothing to be stale about.
  const reset = useRef(counter.reset)
  reset.current = counter.reset
  useEffect(() => {
    if (empty) {
      reset.current()
      setGeneratedFor(null)
    }
  }, [empty])

  function generate() {
    setShowStale(false)
    counter.mutate(ids, { onSuccess: () => setGeneratedFor(signature) })
  }

  return (
    <section className="flex flex-col gap-3">
      <header className="flex items-center gap-2">
        <h2 className="font-display mr-auto text-sm font-medium">Counter-team</h2>
        <button
          type="button"
          // Prevented rather than attempted: an empty team cannot produce a
          // counter team, so the request is never fired and no error is shown.
          disabled={empty || counter.isPending}
          onClick={generate}
          title={empty ? 'Add at least one Pokémon to your team' : undefined}
          className={cn(
            'border-border bg-card h-8 shrink-0 rounded-[8px] border px-3 text-xs font-medium',
            'hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40',
          )}
        >
          {counter.isPending
            ? 'Thinking…'
            : // The count is in the label so the size is known before clicking.
              `Generate${empty ? '' : ` (${ids.length})`}`}
        </button>
      </header>

      {empty ? (
        <p className="text-muted-foreground text-xs">Add at least one Pokémon to your team.</p>
      ) : null}

      {counter.isError ? (
        <ErrorState message="Could not build a counter-team." onRetry={generate} />
      ) : counter.isPending ? (
        // One skeleton per pick that is coming, so the list does not resize.
        <ul className="flex flex-col gap-2">
          {Array.from({ length: Math.max(1, ids.length) }, (_, index) => (
            <li key={index} className="card-surface h-28 p-3">
              <div className="bg-muted skeleton-shimmer relative h-full w-full overflow-hidden rounded" />
            </li>
          ))}
        </ul>
      ) : counter.data ? (
        <div className="flex flex-col gap-2">
          {stale ? (
            // Collapsed rather than merely dimmed. Six answers left on screen
            // for a team of one read as the current answer no matter how faint
            // they are, and the count is the very thing that changed.
            <div className="card-surface flex flex-col gap-2 p-3">
              <p className="text-xs">
                Your team changed since these were generated.
              </p>
              <p className="text-muted-foreground text-[11px]">
                {staleSize} answer{staleSize === 1 ? '' : 's'} for your previous team; your
                team now has {ids.length}.
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={generate}
                  className="border-border bg-card hover:bg-muted h-7 rounded-[8px] border px-2.5 text-[11px] font-medium"
                >
                  Regenerate ({ids.length})
                </button>
                <button
                  type="button"
                  onClick={() => setShowStale((value) => !value)}
                  className="text-muted-foreground hover:text-foreground text-[11px]"
                >
                  {showStale ? 'Hide previous' : 'Show previous'}
                </button>
              </div>
            </div>
          ) : null}

          {/* Nothing is thrown away: the previous answers are one click back. */}
          {!stale || showStale ? (
            <div className={cn('flex flex-col gap-2', stale && 'opacity-50')}>
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
                        best answer{' '}
                        <DisplayName name={entry.best_answer} className="text-foreground" />
                      </span>
                      <MultiplierBadge value={entry.score} />
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <EmptyState
          title="No counter-team yet"
          hint={`Suggests ${ids.length} Pokémon that answer this team, with the reasoning for each.`}
        />
      )}
    </section>
  )
}
