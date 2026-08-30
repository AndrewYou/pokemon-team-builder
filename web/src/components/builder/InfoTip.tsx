import { Info } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/utils'

const WIDTH = 224
const GAP = 6
const EDGE = 8

/**
 * A tooltip that works without a pointer, and outside its own stacking context.
 *
 * One component rather than a hover tooltip plus a separate mobile popover: it
 * opens on hover, on keyboard focus and on tap, which covers every input without
 * branching on a media query that touch laptops get wrong anyway.
 *
 * It is portalled to the body and positioned with `fixed` from the trigger's
 * rect. Positioning it absolutely inside the row is what broke it: the collapsible
 * pick body wraps its content in `overflow-hidden` to animate height, so a
 * tooltip drawn above the trigger fell outside that box and was clipped away --
 * present in the DOM, reported visible, and invisible on screen.
 */
export function InfoTip({
  label,
  children,
  className,
}: {
  label: string
  children: React.ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const id = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const tipRef = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    if (!open) return

    function place() {
      const trigger = triggerRef.current?.getBoundingClientRect()
      if (!trigger) return
      const height = tipRef.current?.offsetHeight ?? 0
      // Above by default, below when there is no room above.
      const above = trigger.top - GAP - height
      setPosition({
        top: above >= EDGE ? above : trigger.bottom + GAP,
        left: Math.min(
          Math.max(EDGE, trigger.left + trigger.width / 2 - WIDTH / 2),
          window.innerWidth - WIDTH - EDGE,
        ),
      })
    }

    place()
    // The panel scrolls under a fixed tooltip, so it has to follow or close.
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!triggerRef.current?.contains(target) && !tipRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
        // Gated on pointerType rather than using mouseenter: a tap also emits
        // synthesised mouse events, which would open the tooltip a moment
        // before the click that follows toggled it shut.
        onPointerEnter={(event) => {
          if (event.pointerType === 'mouse') setOpen(true)
        }}
        onPointerLeave={(event) => {
          if (event.pointerType === 'mouse') setOpen(false)
        }}
        // Keyboard focus only. A tap also focuses the button, and opening here
        // would let the click that follows immediately toggle it shut again.
        onFocus={(event) => {
          if (event.target.matches(':focus-visible')) setOpen(true)
        }}
        onBlur={() => setOpen(false)}
        className={cn(
          'text-muted-foreground hover:text-foreground focus-visible:ring-ring',
          'inline-grid size-4 shrink-0 place-items-center rounded-full',
          'focus-visible:ring-2 focus-visible:outline-none',
          className,
        )}
      >
        <Info aria-hidden className="size-3" />
      </button>
      {open
        ? createPortal(
            <span
              ref={tipRef}
              id={id}
              role="tooltip"
              style={{ top: position.top, left: position.left, width: WIDTH }}
              className={cn(
                'border-border bg-popover text-popover-foreground fixed z-[60] block',
                'rounded-[8px] border p-2 text-[11px] leading-snug shadow-xl',
              )}
            >
              {children}
            </span>,
            document.body,
          )
        : null}
    </>
  )
}
