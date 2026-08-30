/**
 * Verdict vocabulary and colour, in one place.
 *
 * Two voices, because there are two subjects. Inside a pick's detail table the
 * subject is our counter, so the verb is active: "Blacephalon vs Steelix --
 * Dominates". In the coverage strip the subject is the THREAT, so the same verb
 * inverts the meaning: "Steelix Dominates" reads as Steelix winning. Coverage
 * therefore uses the passive form, "Steelix -- Dominated".
 *
 * Both sets are keyed off the one verdict the API sends, so they cannot drift
 * apart or disagree about which colour goes with which word.
 */
export type VerdictKey = 'Dominates' | 'Wins' | 'Trades' | 'Loses'

export const VERDICT_LABELS: Record<
  VerdictKey,
  { active: string; passive: string; badge: string; dot: string; chip: string }
> = {
  Dominates: {
    active: 'Dominates',
    passive: 'Dominated',
    badge: 'text-emerald-400 bg-emerald-400/12',
    dot: 'bg-emerald-400',
    chip: 'border-emerald-400/30 bg-emerald-400/8',
  },
  Wins: {
    active: 'Wins',
    passive: 'Countered',
    badge: 'text-emerald-500/90 bg-emerald-500/10',
    dot: 'bg-emerald-500/70',
    chip: 'border-emerald-500/25 bg-emerald-500/6',
  },
  Trades: {
    active: 'Trades',
    passive: 'Contested',
    badge: 'text-amber-400 bg-amber-400/12',
    dot: 'bg-amber-400',
    chip: 'border-amber-400/40 bg-amber-400/10',
  },
  Loses: {
    // The one that matters. An unanswered threat is the most useful thing the
    // coverage strip can say, so it is the loudest thing in it.
    active: 'Loses',
    passive: 'Unanswered',
    badge: 'text-rose-300 bg-rose-500/20 ring-1 ring-rose-400/50',
    dot: 'bg-rose-400',
    chip: 'border-rose-400/60 bg-rose-500/12',
  },
}

const FALLBACK = {
  active: '',
  passive: '',
  badge: 'text-muted-foreground bg-muted',
  dot: 'bg-muted-foreground/40',
  chip: 'border-border bg-card',
}

export function verdictTone(verdict: string) {
  return VERDICT_LABELS[verdict as VerdictKey] ?? FALLBACK
}

/** The word for a verdict, in the voice the subject calls for. */
export function verdictLabel(verdict: string, voice: 'active' | 'passive'): string {
  return VERDICT_LABELS[verdict as VerdictKey]?.[voice] ?? verdict
}
