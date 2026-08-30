import { formatDistanceToNow } from 'date-fns'
import { Bell, BellOff, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'

import type { AlertGroup } from '@/api/client'
import { useAlerts, useDismissAlert, useDismissAllAlerts } from '@/api/queries'
import { cn } from '@/lib/utils'

import { DisplayName, Sprite } from './primitives'

/** Past nine the exact number stops being useful. */
function badgeLabel(count: number): string {
  return count > 9 ? '9+' : String(count)
}

function relative(iso: string): string {
  // The API sends UTC; without the marker Safari parses it as local time and
  // every alert reads as hours in the future.
  const withZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`
  return formatDistanceToNow(new Date(withZone), { addSuffix: true })
}

function AlertRow({
  group,
  onDismiss,
}: {
  group: AlertGroup
  onDismiss: (changeId: number) => void
}) {
  return (
    <li className="border-border/50 flex gap-3 border-b p-3 last:border-b-0">
      <Sprite
        src={group.sprite_url}
        alt={group.pokemon_name}
        size="sm"
        type={undefined}
      />
      <div className="min-w-0 flex-1">
        <DisplayName name={group.pokemon_name} className="text-xs font-semibold" />
        <p className="text-muted-foreground truncate text-[11px]">
          on {group.affected_teams.map((team) => team.team_name).join(', ')}
        </p>
        <ul className="mt-1.5 flex flex-col gap-1">
          {group.changes.map((change) => (
            <li
              key={change.change_id}
              // Undismissed items are tinted with a dot. Dismissed ones are
              // removed outright rather than greyed, so the list only ever
              // holds things still worth reading.
              className="bg-primary/5 flex items-start gap-2 rounded-[6px] px-1.5 py-1"
            >
              <span aria-hidden className="bg-primary mt-1.5 size-1.5 shrink-0 rounded-full" />
              <span className="min-w-0 flex-1">
                <span className="block text-[11px] leading-snug">{change.message}</span>
                <time
                  dateTime={change.detected_at}
                  className="text-muted-foreground text-[10px]"
                >
                  {relative(change.detected_at)}
                </time>
              </span>
              <button
                type="button"
                onClick={() => onDismiss(change.change_id)}
                aria-label={`Dismiss: ${change.message}`}
                className="text-muted-foreground hover:text-foreground hover:bg-muted grid size-5 shrink-0 place-items-center rounded-[4px]"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      </div>
    </li>
  )
}

/**
 * Alerts as a notification bell, not an inline panel.
 *
 * In the team panel they sat below the primary workflow and scrolled out of
 * view, which is the wrong place for something that arrives on its own
 * schedule. The bell is always visible and the count carries the signal.
 */
export function NotificationBell() {
  const alerts = useAlerts()
  const dismiss = useDismissAlert()
  const dismissAll = useDismissAllAlerts()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const bellRef = useRef<HTMLButtonElement>(null)
  const location = useLocation()

  // The count is changes, not Pokemon: three changes on one Pokemon is three
  // things to read.
  const count = alerts.data?.total_changes ?? 0
  const groups = alerts.data?.groups ?? []

  // Animate only when the number grows, so a dismissal does not bounce.
  const [pop, setPop] = useState(false)
  const previous = useRef(count)
  useEffect(() => {
    if (count > previous.current) {
      setPop(true)
      const timer = setTimeout(() => setPop(false), 220)
      return () => clearTimeout(timer)
    }
    previous.current = count
  }, [count])
  useEffect(() => {
    previous.current = count
  }, [count])

  useEffect(() => setOpen(false), [location.pathname])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false)
        bellRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  function moveFocus(direction: 1 | -1) {
    const items = containerRef.current?.querySelectorAll<HTMLButtonElement>(
      'button[aria-label^="Dismiss:"]',
    )
    if (!items?.length) return
    const active = document.activeElement
    const index = Array.from(items).indexOf(active as HTMLButtonElement)
    const next = index === -1 ? 0 : (index + direction + items.length) % items.length
    items[next].focus()
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={bellRef}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Notifications, ${count} unread`}
        className="border-border bg-card hover:bg-muted relative grid size-8 place-items-center rounded-[8px] border"
      >
        <Bell aria-hidden className="size-4" />
        {count > 0 ? (
          <span
            aria-hidden
            className={cn(
              // A single accent. This is a system signal, not Pokemon data, so
              // it deliberately does not use a type colour.
              'bg-primary text-primary-foreground absolute -top-1.5 -right-1.5 grid min-w-4',
              'tabular place-items-center rounded-full px-1 text-[10px] leading-4 font-semibold',
              'transition-transform duration-200',
              pop && 'scale-125',
            )}
          >
            {badgeLabel(count)}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="Data changes"
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') {
              event.preventDefault()
              moveFocus(1)
            }
            if (event.key === 'ArrowUp') {
              event.preventDefault()
              moveFocus(-1)
            }
          }}
          className={cn(
            'border-border bg-popover z-50 overflow-hidden border shadow-xl',
            // Popover on desktop, full sheet on a phone.
            'max-md:fixed max-md:inset-x-0 max-md:bottom-0 max-md:max-h-[80svh] max-md:rounded-t-[16px]',
            'md:absolute md:top-full md:right-0 md:mt-1 md:w-[380px] md:rounded-[12px]',
          )}
        >
          <div className="border-border flex items-center gap-2 border-b px-3 py-2">
            <h2 className="font-display text-xs font-semibold">Data changes</h2>
            {count > 0 ? (
              <button
                type="button"
                onClick={() => dismissAll.mutate()}
                className="text-muted-foreground hover:text-foreground ml-auto text-[11px]"
              >
                Dismiss all
              </button>
            ) : null}
          </div>

          {count === 0 ? (
            <div className="grid place-items-center gap-1 px-6 py-10 text-center">
              <BellOff aria-hidden className="text-muted-foreground/50 mb-1 size-6" />
              <p className="text-xs font-medium">No recent changes</p>
              <p className="text-muted-foreground text-[11px]">
                We’ll let you know if any of your Pokémon change.
              </p>
            </div>
          ) : (
            <ul className="max-h-[480px] overflow-y-auto max-md:max-h-[60svh]">
              {groups.map((group) => (
                <AlertRow
                  key={group.pokemon_id}
                  group={group}
                  onDismiss={(changeId) => dismiss.mutate(changeId)}
                />
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  )
}
