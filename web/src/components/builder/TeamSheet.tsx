import { useEffect } from 'react'

import { cn } from '@/lib/utils'

/**
 * The overlay the tablet rail and the mobile bar expand into.
 *
 * A sheet rather than a modal dialog: the grid stays visible behind it, so the
 * user keeps their place in a list of 1300 entries.
 */
export function TeamSheet({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <button
        type="button"
        aria-label="Close team panel"
        onClick={onClose}
        className="absolute inset-0 bg-black/50 backdrop-blur-[2px]"
      />
      <div
        role="dialog"
        aria-label="Team"
        className={cn(
          'bg-background border-border absolute inset-x-0 bottom-0 max-h-[85svh] overflow-y-auto',
          'rounded-t-[16px] border-t',
        )}
        // The bar sits on the home indicator otherwise.
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom), 12px)' }}
      >
        <div className="bg-border mx-auto mt-2 h-1 w-10 rounded-full" />
        {children}
      </div>
    </div>
  )
}
