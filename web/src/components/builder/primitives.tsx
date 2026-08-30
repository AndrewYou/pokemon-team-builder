import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** API names arrive lowercase; capitalising in CSS keeps the data untouched. */
export function DisplayName({ name, className }: { name: string; className?: string }) {
  return <span className={cn('capitalize', className)}>{name.replace(/-/g, ' ')}</span>
}

/**
 * A sprite in a gallery mount.
 *
 * The sprites are 96x96 pixel art, so they are rendered with
 * `image-rendering: pixelated`. Crisp pixels inside a clean frame read as a
 * deliberate choice; the browser's default smoothing reads as a bug.
 */
/**
 * A neutral stand-in for a Pokemon with no sprite.
 *
 * A few entries genuinely have a null front_default. The name is always
 * rendered beside this by every caller, so the slot still identifies what it
 * holds -- what must never appear is a technical fallback string like
 * "No sprite", which reads as a bug rather than as missing artwork.
 */
function Silhouette({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={cn('text-muted-foreground/40', className)}>
      <path
        fill="currentColor"
        d="M12 3a9 9 0 0 0-8.94 8h5.1a4 4 0 0 1 7.68 0h5.1A9 9 0 0 0 12 3Zm8.94 10h-5.1a4 4 0 0 1-7.68 0h-5.1A9 9 0 0 0 12 21a9 9 0 0 0 8.94-8ZM12 10a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z"
      />
    </svg>
  )
}

export function Sprite({
  src,
  alt,
  size = 'md',
  type,
}: {
  src: string | null | undefined
  alt: string
  size?: 'xs' | 'sm' | 'md' | 'lg'
  type?: string
}) {
  // The sprites are natively 96x96. Rendering them at exactly that size means
  // one source pixel per CSS pixel -- no scaling artefacts at all -- and the
  // mount supplies the breathing room instead.
  const mount = { xs: 'size-6', sm: 'size-12', md: 'h-32 w-full', lg: 'h-36 w-full' }[size]
  const image = { xs: 'size-6', sm: 'size-10', md: 'size-24', lg: 'size-28' }[size]

  return (
    <div
      data-type={type}
      className={cn('type-tint grid shrink-0 place-items-center rounded-[10px]', mount)}
    >
      {src ? (
        <img src={src} alt={alt} loading="lazy" decoding="async" className={cn('sprite', image)} />
      ) : (
        <Silhouette className={image} />
      )}
    </div>
  )
}

/** A type, as a pill. The saturated colour is used for text and border only. */
export function TypeBadge({ type, className }: { type: string; className?: string }) {
  return (
    <span
      data-type={type}
      className={cn(
        'type-tint inline-flex items-center rounded-full px-2 py-0.5 text-[11px]',
        'font-medium capitalize',
        className,
      )}
      style={{ color: 'var(--type)', borderColor: 'var(--type)' }}
    >
      {type}
    </span>
  )
}

export function TypeBadges({ types, className }: { types: string[]; className?: string }) {
  return (
    <div className={cn('flex flex-wrap gap-1', className)}>
      {types.map((type) => (
        <TypeBadge key={type} type={type} />
      ))}
    </div>
  )
}

/**
 * Verdict colours, in one place.
 *
 * Coloured by outcome, never by type: this is analysis, not Pokemon data, and
 * reusing the type palette would suggest the colour meant something about the
 * Pokemon rather than about the fight. The badge, the coverage chips and the
 * summary dots all read from here so they cannot drift apart.
 */
export const VERDICT_TONE: Record<string, { badge: string; dot: string; chip: string }> = {
  Dominates: {
    badge: 'text-emerald-400 bg-emerald-400/12',
    dot: 'bg-emerald-400',
    chip: 'border-emerald-400/30 bg-emerald-400/8',
  },
  Wins: {
    badge: 'text-emerald-500/90 bg-emerald-500/10',
    dot: 'bg-emerald-500/70',
    chip: 'border-emerald-500/25 bg-emerald-500/6',
  },
  Trades: {
    badge: 'text-amber-400 bg-amber-400/12',
    dot: 'bg-amber-400',
    chip: 'border-amber-400/40 bg-amber-400/10',
  },
  Loses: {
    badge: 'text-rose-400/90 bg-rose-400/10',
    dot: 'bg-rose-400',
    chip: 'border-rose-400/40 bg-rose-400/10',
  },
}

const FALLBACK_TONE = {
  badge: 'text-muted-foreground bg-muted',
  dot: 'bg-muted-foreground/40',
  chip: 'border-border bg-card',
}

export function verdictTone(verdict: string) {
  return VERDICT_TONE[verdict] ?? FALLBACK_TONE
}

/** The verdict for a matchup. */
export function VerdictBadge({ verdict, className }: { verdict: string; className?: string }) {
  return (
    <span
      className={cn(
        'inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold',
        verdictTone(verdict).badge,
        className,
      )}
    >
      {verdict}
    </span>
  )
}

/**
 * A pick's whole scorecard as one row of dots, in team order.
 *
 * The point of the collapsed row: six green dots reads "handles everything" and
 * five green with one red reads "one gap", neither of which needs expanding.
 */
export function VerdictDots({
  answers,
  className,
}: {
  answers: { enemy_id: number; enemy_name: string; verdict: string }[]
  className?: string
}) {
  return (
    <span className={cn('flex items-center gap-1', className)} aria-hidden>
      {answers.map((answer) => (
        <span
          key={answer.enemy_id}
          title={`${answer.enemy_name}: ${answer.verdict}`}
          className={cn('size-1.5 rounded-full', verdictTone(answer.verdict).dot)}
        />
      ))}
    </span>
  )
}

/**
 * Turn margin: how many turns to spare we win by.
 *
 * A signed integer reads instantly where a 0-1 score does not. Null means one
 * side can never knock the other out, so a difference of turns is undefined --
 * rendered in words rather than as a very large number.
 */
export function MarginCell({
  margin,
  ourTurns,
  theirTurns,
}: {
  margin: number | null | undefined
  ourTurns: number | null | undefined
  theirTurns: number | null | undefined
}) {
  if (margin === null || margin === undefined) {
    const text = ourTurns == null ? "Can't KO" : 'Never KOs us'
    return <span className="text-muted-foreground text-[10px]">{text}</span>
  }
  return (
    <span
      className={cn(
        'tabular text-xs font-semibold',
        margin > 0 ? 'text-emerald-500' : margin === 0 ? 'text-amber-400' : 'text-rose-400',
      )}
      title={`We KO in ${ourTurns}; they need ${theirTurns}`}
    >
      {margin > 0 ? `+${margin}` : margin}
    </span>
  )
}

/** A skeleton block. Matching the real dimensions avoids a layout jump. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('bg-muted skeleton-shimmer relative overflow-hidden rounded-md', className)}
    />
  )
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="border-border/60 grid place-items-center gap-2 rounded-[12px] border border-dashed px-6 py-12 text-center">
      <p className="font-display text-sm font-medium">{title}</p>
      {hint ? <p className="text-muted-foreground max-w-sm text-xs">{hint}</p> : null}
      {action}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="border-destructive/30 bg-destructive/5 grid place-items-center gap-3 rounded-[12px] border px-6 py-10 text-center">
      <p className="text-sm">{message}</p>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="border-border hover:bg-muted rounded-[8px] border px-3 py-1.5 text-xs"
        >
          Try again
        </button>
      ) : null}
    </div>
  )
}
