import { Info } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

/**
 * A tooltip that also works without a pointer.
 *
 * One component rather than a hover tooltip plus a separate mobile popover:
 * it opens on hover, on keyboard focus, and on tap, which covers every input
 * without branching on a media query that touch laptops get wrong anyway.
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
  const id = useId()
  const containerRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
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
    <span
      ref={containerRef}
      className={cn('relative inline-flex', className)}
      // Gated on pointerType rather than using mouseenter: a tap also emits
      // synthesised mouse events, which would open the tooltip a moment before
      // the click that follows toggled it shut.
      onPointerEnter={(event) => {
        if (event.pointerType === 'mouse') setOpen(true)
      }}
      onPointerLeave={(event) => {
        if (event.pointerType === 'mouse') setOpen(false)
      }}
    >
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
        // Keyboard focus only. A tap also focuses the button, and opening here
        // would let the click that follows immediately toggle it shut again.
        onFocus={(event) => {
          if (event.target.matches(':focus-visible')) setOpen(true)
        }}
        onBlur={() => setOpen(false)}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-grid size-4 place-items-center rounded-full focus-visible:ring-2 focus-visible:outline-none"
      >
        <Info aria-hidden className="size-3" />
      </button>
      {open ? (
        <span
          id={id}
          role="tooltip"
          className={cn(
            'border-border bg-popover absolute bottom-full left-1/2 z-50 mb-1.5 w-56',
            '-translate-x-1/2 rounded-[8px] border p-2 text-[11px] leading-snug shadow-xl',
          )}
        >
          {children}
        </span>
      ) : null}
    </span>
  )
}
