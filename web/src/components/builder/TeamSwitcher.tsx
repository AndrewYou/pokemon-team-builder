import { useState } from 'react'

import type { TeamRead } from '@/api/client'
import { useCreateTeam, useDeleteTeam, useRenameTeam } from '@/api/queries'
import { cn } from '@/lib/utils'

const CONTROL = 'border-border bg-card h-8 rounded-[8px] border px-2.5 text-xs'

export function TeamSwitcher({
  teams,
  activeId,
  onSelect,
}: {
  teams: TeamRead[]
  activeId: number | null
  onSelect: (id: number | null) => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState('')

  const create = useCreateTeam()
  const rename = useRenameTeam()
  const remove = useDeleteTeam()
  const active = teams.find((team) => team.id === activeId)

  async function handleCreate() {
    const team = await create.mutateAsync(`Team ${teams.length + 1}`)
    onSelect(team.id)
  }

  async function handleRename() {
    if (!active || !draft.trim()) return setRenaming(false)
    await rename.mutateAsync({ id: active.id, name: draft.trim() })
    setRenaming(false)
  }

  async function handleDelete() {
    if (!active) return
    await remove.mutateAsync(active.id)
    onSelect(teams.find((team) => team.id !== active.id)?.id ?? null)
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {renaming && active ? (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void handleRename()
          }}
          className="flex items-center gap-2"
        >
          <input
            autoFocus
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => void handleRename()}
            aria-label="Team name"
            className={cn(CONTROL, 'w-40')}
          />
        </form>
      ) : (
        <>
          <select
            value={activeId ?? ''}
            onChange={(event) => onSelect(Number(event.target.value) || null)}
            aria-label="Active team"
            className={cn(CONTROL, 'max-w-44 font-medium')}
          >
            {teams.length === 0 ? <option value="">No teams yet</option> : null}
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
          {active ? (
            <button
              type="button"
              onClick={() => {
                setDraft(active.name)
                setRenaming(true)
              }}
              className={cn(CONTROL, 'text-muted-foreground hover:text-foreground')}
            >
              Rename
            </button>
          ) : null}
        </>
      )}

      <button
        type="button"
        onClick={() => void handleCreate()}
        disabled={create.isPending}
        className={cn(CONTROL, 'hover:bg-muted font-medium')}
      >
        New team
      </button>

      {active ? (
        <button
          type="button"
          onClick={() => void handleDelete()}
          className={cn(CONTROL, 'text-muted-foreground hover:text-destructive')}
        >
          Delete
        </button>
      ) : null}
    </div>
  )
}
