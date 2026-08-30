import { ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { CounterAnswer, CounterPick, CoverageEntry, TeamMember } from '@/api/client'
import { useCounterTeam } from '@/api/queries'
import { cn } from '@/lib/utils'

import {
  DisplayName,
  EmptyState,
  ErrorState,
  MarginCell,
  Sprite,
  TypeBadges,
  VerdictBadge,
  VerdictDots,
  verdictTone,
} from './primitives'
import { InfoTip } from './InfoTip'

const MARGIN_HELP =
  'How many attacks the enemy runs short by. +3 means they need three more ' +
  'turns to knock us out than they actually get, counting the one they lose ' +
  'when we move first. Higher is better; negative means we lose the exchange.'

const VERDICT_HELP = (
  <>
    <strong>Dominates</strong> +3, or they never land a hit · <strong>Wins</strong> +1 to +2 ·{' '}
    <strong>Trades</strong> 0 · <strong>Loses</strong> below 0
  </>
)

/** The percentages, kept off the scan path and available on demand. */
function detail(answer: CounterAnswer): string {
  const dealt = `deals ${Math.round(answer.damage_fraction * 100)}% per turn`
  const taken =
    answer.enemy_turns === 0
      ? 'takes nothing back'
      : `takes ${Math.round(answer.incoming_fraction * 100)}% per turn, over ${answer.enemy_turns} ` +
        `turn${answer.enemy_turns === 1 ? '' : 's'}`
  return `${dealt}; ${taken}`
}

/**
 * One pick's reasoning, as a small table.
 *
 * The 0-1 score is a good sort key and a poor thing to read, so it stays in the
 * API response and out of this table. Turn margin is what a person can act on.
 */
function AnswerTable({ answers }: { answers: CounterAnswer[] }) {
  return (
    <table className="w-full text-left text-[11px]">
      <thead className="text-muted-foreground">
        <tr>
          <th scope="col" className="font-normal">
            Against
          </th>
          <th scope="col" className="font-normal">
            <span className="inline-flex items-center gap-1">
              Result
              <InfoTip label="What the verdicts mean">{VERDICT_HELP}</InfoTip>
            </span>
          </th>
          <th scope="col" className="w-14 font-normal">
            <span className="inline-flex items-center gap-1">
              Margin
              <InfoTip label="What turn margin means">{MARGIN_HELP}</InfoTip>
            </span>
          </th>
          <th scope="col" className="hidden font-normal sm:table-cell">
            Why
          </th>
        </tr>
      </thead>
      <tbody>
        {[...answers]
          .sort((a, b) => b.multiplier - a.multiplier)
          .map((answer) => (
            <tr key={answer.enemy_id} className="border-border/50 border-t align-top">
              <td className="py-1">
                <DisplayName name={answer.enemy_name} />
              </td>
              <td className="py-1">
                <VerdictBadge verdict={answer.verdict} />
              </td>
              <td className="py-1">
                <MarginCell
                  margin={answer.margin}
                  ourTurns={answer.our_turns}
                  theirTurns={answer.their_turns}
                />
              </td>
              {/* The percentages live in the title, not on the scan path. */}
              <td className="hidden py-1 sm:table-cell" title={detail(answer)}>
                <span className="text-foreground/80">{answer.rationale}</span>
                {answer.qualifier ? (
                  <span className="text-muted-foreground"> — {answer.qualifier}</span>
                ) : null}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  )
}

/**
 * Coverage as a strip of enemies rather than a list of picks.
 *
 * The old panel said "best answer Blacephalon" six times: true, and useless.
 * Coverage exists to show GAPS, so each enemy carries its own best verdict and
 * anything short of a win is called out above the strip.
 */
function CoverageStrip({
  coverage,
  onFocusPick,
}: {
  coverage: CoverageEntry[]
  onFocusPick: (pickId: number) => void
}) {
  const gaps = coverage.filter(
    (entry) => entry.best_verdict === 'Loses' || entry.best_verdict === 'Trades',
  )

  return (
    <div className="card-surface flex flex-col gap-2 p-3">
      <div className="flex items-baseline gap-2">
        <h3 className="text-muted-foreground text-[11px] font-medium">Coverage</h3>
        {gaps.length ? (
          <p className="text-[11px] text-amber-400">
            {gaps.length} unanswered:{' '}
            <span className="capitalize">
              {gaps.map((entry) => entry.enemy_name.replace(/-/g, ' ')).join(', ')}
            </span>
          </p>
        ) : (
          <p className="text-muted-foreground text-[11px]">every threat answered</p>
        )}
      </div>
      <ul className="flex flex-wrap gap-1">
        {coverage.map((entry) => (
          <li key={entry.enemy_id}>
            <button
              type="button"
              onClick={() => onFocusPick(entry.best_answer_id)}
              title={`${entry.enemy_name}: ${entry.best_verdict} — best answer ${entry.best_answer}`}
              className={cn(
                'flex h-6 items-center gap-1 rounded-full border pr-1.5 pl-0.5',
                'focus-visible:ring-ring hover:brightness-125 focus-visible:ring-2 focus-visible:outline-none',
                verdictTone(entry.best_verdict).chip,
              )}
            >
              <Sprite src={entry.enemy_sprite_url} alt={entry.enemy_name} size="xs" />
              <DisplayName name={entry.enemy_name} className="text-[10px]" />
              <VerdictBadge verdict={entry.best_verdict} className="px-1 py-0 text-[9px]" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * One pick, collapsed to a single row until asked.
 *
 * Six picks with a six-row table each is more than fits on a screen, so the
 * default is the whole team at a glance and the detail is one click away. Height
 * is animated with a grid row rather than max-height, so it does not depend on
 * guessing the content height; the global reduced-motion rule zeroes it.
 */
function PickCard({
  pick,
  open,
  onToggle,
  cardRef,
}: {
  pick: CounterPick
  open: boolean
  onToggle: () => void
  cardRef: (node: HTMLLIElement | null) => void
}) {
  const primary = pick.types[0]
  const bodyId = `pick-${pick.id}-detail`

  return (
    <li ref={cardRef} data-type={primary} className="card-surface relative flex flex-col">
      <span
        aria-hidden
        className="absolute inset-y-3 left-0 w-0.5 rounded-full"
        style={{ background: 'var(--type)' }}
      />
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={bodyId}
        className="focus-visible:ring-ring flex items-center gap-3 p-3 text-left focus-visible:ring-2 focus-visible:outline-none"
      >
        <Sprite src={pick.sprite_url} alt={pick.name} size="sm" type={primary} />
        <div className="min-w-0 flex-1">
          <DisplayName
            name={pick.name}
            className="font-display block truncate text-sm font-medium"
          />
          <div className="mt-1 flex items-center gap-2">
            <TypeBadges types={pick.types} />
            <VerdictDots answers={pick.answers} />
          </div>
        </div>
        <ChevronDown
          aria-hidden
          className={cn(
            'text-muted-foreground size-4 shrink-0 transition-transform duration-200',
            open && 'rotate-180',
          )}
        />
      </button>
      <div
        id={bodyId}
        className={cn(
          'grid transition-[grid-template-rows] duration-200 ease-out',
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]',
        )}
      >
        <div className="overflow-hidden">
          <div className="px-3 pb-3">
            <AnswerTable answers={pick.answers} />
          </div>
        </div>
      </div>
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

  // Which picks are open. A set, not a single id: this is not an exclusive
  // accordion, because comparing two picks means having both on screen.
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(new Set())
  const cards = useRef(new Map<number, HTMLLIElement>())

  const registerCard = (id: number) => (node: HTMLLIElement | null) => {
    if (node) cards.current.set(id, node)
    else cards.current.delete(id)
  }

  // A coverage chip names an enemy; the useful destination is the pick that
  // answers it, opened and in view.
  function focusPick(pickId: number) {
    setExpanded((current) => new Set(current).add(pickId))
    // After the row has been told to open, so the scroll lands on its final
    // position rather than its collapsed one.
    requestAnimationFrame(() => {
      cards.current.get(pickId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    })
  }

  function toggle(pickId: number) {
    setExpanded((current) => {
      const next = new Set(current)
      if (!next.delete(pickId)) next.add(pickId)
      return next
    })
  }
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
    // A new result is a new set of picks; carrying the old expansion over
    // would open whichever rows happen to share an index.
    setExpanded(new Set())
    counter.mutate(ids, { onSuccess: () => setGeneratedFor(signature) })
  }

  const allOpen =
    counter.data != null &&
    counter.data.picks.length > 0 &&
    counter.data.picks.every((pick) => expanded.has(pick.id))

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
              <p className="text-xs">Your team changed since these were generated.</p>
              <p className="text-muted-foreground text-[11px]">
                {staleSize} answer{staleSize === 1 ? '' : 's'} for your previous team; your team now
                has {ids.length}.
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
              <CoverageStrip coverage={counter.data.coverage} onFocusPick={focusPick} />
              <div className="flex items-center justify-between">
                <h3 className="text-muted-foreground text-[11px] font-medium">
                  {counter.data.picks.length} pick{counter.data.picks.length === 1 ? '' : 's'}
                </h3>
                <button
                  type="button"
                  onClick={() =>
                    setExpanded(
                      allOpen ? new Set() : new Set(counter.data!.picks.map((pick) => pick.id)),
                    )
                  }
                  className="text-muted-foreground hover:text-foreground text-[11px]"
                >
                  {allOpen ? 'Collapse all' : 'Expand all'}
                </button>
              </div>
              <ul className="flex flex-col gap-2">
                {counter.data.picks.map((pick) => (
                  <PickCard
                    key={pick.id}
                    pick={pick}
                    open={expanded.has(pick.id)}
                    onToggle={() => toggle(pick.id)}
                    cardRef={registerCard(pick.id)}
                  />
                ))}
              </ul>
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
