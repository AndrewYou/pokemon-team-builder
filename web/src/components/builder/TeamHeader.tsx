import { useEffect, useRef, useState } from 'react'

import type { TeamRead } from '@/api/client'
import { useCreateTeam, useDeleteTeam, useRenameTeam } from '@/api/queries'
import { cn } from '@/lib/utils'


/**
 * The team's name IS the heading, and the only control for it.
 *
 * A static "Your team" label beside a separate dropdown is two controls for
 * one piece of state, and the label lies the moment the selection is not the
 * default. Here the heading renders the selected team, the chevron opens the
 * switcher, and the pencil edits in place.
 */
export function TeamHeader({
  teams,
  team,
  onSelect,
}: {
  teams: TeamRead[]
  team: TeamRead | null
  onSelect: (id: number | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const rename = useRenameTeam()
  const create = useCreateTeam()
  const remove = useDeleteTeam()

  function beginEdit(name: string) {
    setDraft(name)
    setEditing(true)
    setOpen(false)
  }

  // Select the text so typing replaces the default rather than appending to it.
  useEffect(() => {
    if (editing) inputRef.current?.select()
  }, [editing])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  function commit() {
    if (!team) return setEditing(false)
    const next = draft.trim()
    setEditing(false)
    // An empty name is rejected rather than saved: reverting is less
    // surprising than a team called "".
    if (!next || next === team.name) return
    rename.mutate({ id: team.id, name: next })
  }

  async function createTeam() {
    setOpen(false)
    // No dialog. A default name lands immediately and the heading opens for
    // editing with the text selected, so typing over it is the same number of
    // keystrokes as filling in a modal would have been.
    const created = await create.mutateAsync(`Team ${teams.length + 1}`)
    onSelect(created.id)
    beginEdit(created.name)
  }

  async function deleteTeam(id: number) {
    const remaining = teams.filter((candidate) => candidate.id !== id)
    await remove.mutateAsync(id)
    setConfirmingDelete(null)
    setOpen(false)
    if (remaining.length === 0) {
      // The panel must never render with nothing selected.
      const created = await create.mutateAsync('My team')
      onSelect(created.id)
      return
    }
    const next = [...remaining].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
    onSelect(next.id)
  }

  if (editing && team) {
    return (
      <input
        ref={inputRef}
        value={draft}
        autoFocus
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') commit()
          if (event.key === 'Escape') setEditing(false)
        }}
        aria-label="Team name"
        className={cn(
          'font-display border-border bg-card h-8 w-full rounded-[8px] border px-2',
          'text-sm font-semibold focus-visible:ring-ring focus-visible:ring-1 focus-visible:outline-none',
        )}
      />
    )
  }

  return (
    <div ref={containerRef} className="relative">
      <div className="group flex items-center gap-1">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-haspopup="listbox"
          title={team?.name ?? 'No team'}
          className="hover:bg-muted -ml-1 flex min-w-0 items-center gap-1 rounded-[8px] px-1 py-0.5"
        >
          <h2 className="font-display truncate text-sm font-semibold">
            {team?.name ?? 'No team'}
          </h2>
          <span aria-hidden className="text-muted-foreground shrink-0 text-[10px]">
            ▾
          </span>
        </button>
        {team ? (
          <button
            type="button"
            onClick={() => beginEdit(team.name)}
            aria-label={`Rename ${team.name}`}
            className={cn(
              'text-muted-foreground hover:text-foreground hover:bg-muted grid size-6 shrink-0',
              'place-items-center rounded-[6px] text-[11px] opacity-0 transition-opacity',
              'group-hover:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100',
            )}
          >
            ✎
          </button>
        ) : null}
      </div>

      {open ? (
        <div
          role="listbox"
          className={cn(
            'border-border bg-popover absolute top-full left-0 z-30 mt-1 w-72 overflow-hidden',
            'rounded-[12px] border shadow-xl',
          )}
        >
          <ul className="max-h-72 overflow-y-auto">
            {teams.map((candidate) => (
              <li key={candidate.id}>
                <div
                  className={cn(
                    'hover:bg-muted flex items-center gap-2 px-2 py-1.5',
                    candidate.id === team?.id && 'bg-muted/60',
                  )}
                >
                  <button
                    type="button"
                    role="option"
                    aria-selected={candidate.id === team?.id}
                    onClick={() => {
                      onSelect(candidate.id)
                      setOpen(false)
                    }}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-medium" title={candidate.name}>
                        {candidate.name}
                      </p>
                      <p className="text-muted-foreground tabular text-[10px]">
                        {candidate.members.length}/6
                      </p>
                    </div>
                    {/* A mini sprite strip, so teams are told apart by their
                        contents rather than by name alone. */}
                    <div className="flex -space-x-1.5">
                      {candidate.members.slice(0, 6).map((member) => (
                        <img
                          key={member.pokemon_id}
                          src={member.sprite_url ?? undefined}
                          alt=""
                          className="sprite bg-muted size-6 rounded-full"
                        />
                      ))}
                    </div>
                  </button>
                  {confirmingDelete === candidate.id ? (
                    <span className="flex shrink-0 items-center gap-1">
                      <button
                        type="button"
                        onClick={() => void deleteTeam(candidate.id)}
                        className="text-destructive rounded-[6px] px-1.5 py-0.5 text-[10px] font-medium"
                      >
                        Delete
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmingDelete(null)}
                        className="text-muted-foreground rounded-[6px] px-1 py-0.5 text-[10px]"
                      >
                        Cancel
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      // Confirmed, because deleting cascades to the roster.
                      onClick={() => setConfirmingDelete(candidate.id)}
                      aria-label={`Delete ${candidate.name}`}
                      className="text-muted-foreground hover:text-destructive shrink-0 rounded-[6px] px-1.5 text-xs"
                    >
                      ×
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => void createTeam()}
            className="border-border hover:bg-muted w-full border-t px-3 py-2 text-left text-xs font-medium"
          >
            + New team
          </button>
        </div>
      ) : null}
    </div>
  )
}