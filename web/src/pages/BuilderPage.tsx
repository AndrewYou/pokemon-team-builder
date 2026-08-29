import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { PokemonSummary, TeamMember } from '@/api/client'
import { useCreateTeam, useSetRoster, useTeams } from '@/api/queries'
import { AlertBanner } from '@/components/builder/AlertBanner'
import { Catalog } from '@/components/builder/Catalog'
import { CardBody } from '@/components/builder/PokemonCard'
import { CounterTeam } from '@/components/builder/CounterTeam'
import { ErrorState, Sprite } from '@/components/builder/primitives'
import { MAX_SLOTS, TeamSlots } from '@/components/builder/TeamSlots'
import { TeamSwitcher } from '@/components/builder/TeamSwitcher'
import { ThemeToggle } from '@/components/builder/ThemeToggle'

const SAVE_DEBOUNCE_MS = 400

export default function BuilderPage() {
  const teams = useTeams()
  const setRoster = useSetRoster()
  const [activeId, setActiveId] = useState<number | null>(null)
  const [dragging, setDragging] = useState<PokemonSummary | TeamMember | null>(null)

  const activeTeam = teams.data?.find((team) => team.id === activeId) ?? teams.data?.[0] ?? null
  const members = useMemo(() => activeTeam?.members ?? [], [activeTeam])

  useEffect(() => {
    if (activeId === null && activeTeam) setActiveId(activeTeam.id)
  }, [activeId, activeTeam])

  // A first-time visitor gets a team without asking for one, so the six slots
  // are there to drag into immediately. Otherwise the first thing anyone sees
  // is an empty state asking them to press a button, and the slots -- the point
  // of the screen -- are not on it.
  const createTeam = useCreateTeam()
  const bootstrapped = useRef(false)
  useEffect(() => {
    if (teams.isSuccess && teams.data.length === 0 && !bootstrapped.current) {
      bootstrapped.current = true
      createTeam.mutate('My team', { onSuccess: (team) => setActiveId(team.id) })
    }
  }, [teams.isSuccess, teams.data, createTeam])

  // A drag produces a whole new ordering, and a reorder can fire several times
  // in quick succession. The debounce collapses those into one PUT; the
  // optimistic update means the UI never waits for it.
  const pending = useRef<number[] | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  function persist(pokemonIds: number[]) {
    if (!activeTeam) return
    pending.current = pokemonIds
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      if (pending.current) {
        setRoster.mutate({ id: activeTeam.id, pokemonIds: pending.current })
        pending.current = null
      }
    }, SAVE_DEBOUNCE_MS)
  }

  // Pointer needs a small activation distance or a click reads as a drag.
  // Keyboard is enabled deliberately: drag and drop that only works with a
  // mouse excludes anyone who does not use one.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  function handleDragStart(event: DragStartEvent) {
    const data = event.active.data.current
    setDragging((data?.pokemon ?? data?.member ?? null) as PokemonSummary | TeamMember | null)
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    setDragging(null)
    if (!over || !activeTeam) return

    const activeIdStr = String(active.id)
    const overIdStr = String(over.id)

    // Reordering within the roster.
    if (activeIdStr.startsWith('member-')) {
      const from = members.findIndex((m) => `member-${m.pokemon_id}` === activeIdStr)
      const to = members.findIndex((m) => `member-${m.pokemon_id}` === overIdStr)
      if (from === -1 || to === -1 || from === to) return
      persist(arrayMove(members, from, to).map((m) => m.pokemon_id))
      return
    }

    // Adding from the catalog.
    if (activeIdStr.startsWith('catalog-') && overIdStr.startsWith('slot-')) {
      const pokemon = active.data.current?.pokemon as PokemonSummary | undefined
      if (!pokemon) return
      if (members.some((m) => m.pokemon_id === pokemon.id)) return
      if (members.length >= MAX_SLOTS) return
      persist([...members.map((m) => m.pokemon_id), pokemon.id])
    }
  }

  function removeMember(pokemonId: number) {
    persist(members.filter((m) => m.pokemon_id !== pokemonId).map((m) => m.pokemon_id))
  }

  const draggingType =
    dragging && 'types' in dragging ? (dragging.types[0] as string | undefined) : undefined

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDragging(null)}
    >
      <div className="bg-background text-foreground min-h-svh">
        <header className="border-border/60 sticky top-0 z-20 border-b backdrop-blur-md">
          <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-4 py-3">
            <h1 className="font-display text-sm font-semibold tracking-tight">Team Builder</h1>
            <span className="text-muted-foreground hidden text-xs sm:inline">
              Drag a Pokémon into a slot
            </span>
            <div className="ml-auto flex items-center gap-2">
              <ThemeToggle />
            </div>
          </div>
        </header>

        <main className="mx-auto flex max-w-[1400px] flex-col gap-4 px-4 py-4">
          <AlertBanner />

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="order-2 min-w-0 lg:order-1">
              <Catalog rosterFull={members.length >= MAX_SLOTS} />
            </div>

            <aside className="order-1 flex flex-col gap-4 lg:order-2">
              <section className="flex flex-col gap-3">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-display text-sm font-medium">Your team</h2>
                  <span className="text-muted-foreground tabular text-xs">
                    {members.length}/{MAX_SLOTS}
                  </span>
                </div>

                {teams.isError ? (
                  <ErrorState
                    message="Could not load your teams."
                    onRetry={() => void teams.refetch()}
                  />
                ) : teams.isPending ? (
                  <ul className="flex flex-col gap-2">
                    {Array.from({ length: MAX_SLOTS }, (_, index) => (
                      <li
                        key={index}
                        className="bg-muted skeleton-shimmer relative h-[60px] overflow-hidden rounded-[12px]"
                      />
                    ))}
                  </ul>
                ) : (
                  <TeamSlots
                    members={members}
                    activeType={draggingType}
                    onRemove={removeMember}
                  />
                )}

                <TeamSwitcher
                  teams={teams.data ?? []}
                  activeId={activeTeam?.id ?? null}
                  onSelect={setActiveId}
                />
              </section>

              <CounterTeam members={members} />
            </aside>
          </div>
        </main>
      </div>

      {/* Rendered detached from the grid, so it can lift above everything.
          This is the one place a shadow is used: elevation means "in hand". */}
      <DragOverlay dropAnimation={{ duration: 180, easing: 'cubic-bezier(0.16,1,0.3,1)' }}>
        {dragging ? (
          <div className="w-[180px] rotate-2 scale-[1.04] cursor-grabbing">
            {'stats' in dragging ? (
              <CardBody pokemon={dragging} dragging />
            ) : (
              <div className="card-surface flex items-center gap-3 p-2 shadow-2xl">
                <Sprite
                  src={dragging.sprite_url}
                  alt={dragging.name}
                  size="sm"
                  type={dragging.types[0]}
                />
                <span className="font-display truncate text-sm capitalize">{dragging.name}</span>
              </div>
            )}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
