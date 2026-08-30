import { useEffect } from 'react'
import { createPortal } from 'react-dom'

/**
 * A transient confirmation with a way back.
 *
 * Used instead of a "Are you sure?" dialog. Clearing a roster is reversible and
 * low-stakes, and a modal on every clear trains people to click through it --
 * which is exactly what makes the one destructive dialog that matters get
 * dismissed unread too.
 */
export function UndoToast({
  message,
  onUndo,
  onDismiss,
  duration = 6000,
}: {
  message: string
  onUndo: () => void
  onDismiss: () => void
  duration?: number
}) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, duration)
    return () => clearTimeout(timer)
  }, [onDismiss, duration])

  return createPortal(
    <div
      // polite, not assertive: this confirms something the user just did, so it
      // should not interrupt whatever a screen reader is mid-sentence on.
      role="status"
      aria-live="polite"
      className="fixed bottom-4 left-1/2 z-[60] -translate-x-1/2"
      style={{ bottom: 'max(env(safe-area-inset-bottom), 1rem)' }}
    >
      <div className="border-border bg-popover flex items-center gap-3 rounded-[10px] border px-3 py-2 shadow-xl">
        <span className="text-xs">{message}</span>
        <button
          type="button"
          onClick={onUndo}
          className="hover:bg-muted rounded-[6px] px-2 py-0.5 text-xs font-semibold underline-offset-2 hover:underline"
        >
          Undo
        </button>
      </div>
    </div>,
    document.body,
  )
}
