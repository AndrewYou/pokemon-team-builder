import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  MeasuringStrategy,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type DragStartEvent,
  type ScreenReaderInstructions,
} from '@dnd-kit/core'
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { GripVertical } from 'lucide-react'
import { createPortal } from 'react-dom'

import type { PokemonSummary, TeamMember } from '@/api/client'
import {
  applyOptimisticRoster,
  useCreateTeam,
  useSetRoster,
  useTeams,
  type RosterEntry,
} from '@/api/queries'
import { Catalog } from '@/components/builder/Catalog'
import { CardBody } from '@/components/builder/PokemonCard'
import { ErrorState, Sprite, TypeBadges } from '@/components/builder/primitives'
import { TeamBar, TeamRail } from '@/components/builder/TeamDock'
import { TeamPanel } from '@/components/builder/TeamPanel'
import { TeamSheet } from '@/components/builder/TeamSheet'
import { MAX_SLOTS } from '@/components/builder/TeamSlots'
import { NotificationBell } from '@/components/builder/NotificationBell'
import { ThemeToggle } from '@/components/builder/ThemeToggle'
import { useSelectedTeam } from '@/lib/selected-team'
import { cn } from '@/lib/utils'

const SAVE_DEBOUNCE_MS = 400

/** A roster entry carries what a slot needs to draw, not just an id. */
function toEntry(source: TeamMember | PokemonSummary): RosterEntry {
  return {
    pokemon_id: 'pokemon_id' in source ? source.pokemon_id : source.id,
    name: source.name,
    sprite_url: source.sprite_url,
    types: source.types,
  }
}

export default function BuilderPage() {
  const teams = useTeams()
  const setRoster = useSetRoster()
  const createTeam = useCreateTeam()
  const queryClient = useQueryClient()
  const { team, select } = useSelectedTeam(teams.data)
  const [dragging, setDragging] = useState<PokemonSummary | TeamMember | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)

  // The grid scrolls, not the page. Sticky alone still leaves the user
  // fighting scroll position when they drag from the bottom of a long list.
  const gridRef = useRef<HTMLDivElement>(null)

  const members = useMemo(() => team?.members ?? [], [team])
  const rosterFull = members.length >= MAX_SLOTS

  // The panel must never render with no team selected.
  const bootstrapped = useRef(false)
  useEffect(() => {
    if (teams.isSuccess && teams.data.length === 0 && !bootstrapped.current) {
      bootstrapped.current = true
      createTeam.mutate('My team', { onSuccess: (created) => select(created.id) })
    }
  }, [teams.isSuccess, teams.data, createTeam, select])

  const pending = useRef<RosterEntry[] | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const persist = useCallback(
    (entries: RosterEntry[]) => {
      if (!team) return
      // The UI updates now; only the PUT is debounced. Deferring both would
      // leave a click showing nothing for the length of the debounce, and the
      // next action would read a roster this one had not written yet.
      applyOptimisticRoster(queryClient, team.id, entries)
      pending.current = entries
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        if (pending.current) {
          setRoster.mutate({ id: team.id, entries: pending.current })
          pending.current = null
        }
      }, SAVE_DEBOUNCE_MS)
    },
    [team, setRoster, queryClient],
  )

  const addPokemon = useCallback(
    (pokemon: PokemonSummary) => {
      if (rosterFull || members.some((member) => member.pokemon_id === pokemon.id)) return
      persist([...members.map(toEntry), toEntry(pokemon)])
    },
    [members, rosterFull, persist],
  )

  const removeMember = useCallback(
    (pokemonId: number) => {
      persist(members.filter((member) => member.pokemon_id !== pokemonId).map(toEntry))
    },
    [members, persist],
  )

  // Mouse and touch are separate sensors rather than one PointerSensor,
  // because they need different activation rules. A press-and-hold on desktop
  // makes reordering feel sluggish; distance-based activation on touch
  // swallows taps and scrolls as drags.
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const positionOf = useCallback(
    (id: string | number) =>
      members.findIndex((member) => `member-${member.pokemon_id}` === String(id)) + 1,
    [members],
  )

  const nameOf = useCallback(
    (id: string | number) =>
      members.find((member) => `member-${member.pokemon_id}` === String(id))?.name ?? 'Pokémon',
    [members],
  )

  // dnd-kit's defaults describe items as "draggable item member-25". These say
  // what a person would say.
  const announcements: Announcements = useMemo(
    () => ({
      onDragStart: ({ active }) =>
        `Picked up ${nameOf(active.id)}, position ${positionOf(active.id)} of ${members.length}.`,
      onDragOver: ({ active, over }) =>
        over && over.id !== active.id
          ? `${nameOf(active.id)} moved to position ${positionOf(over.id)} of ${members.length}.`
          : undefined,
      onDragEnd: ({ active, over }) =>
        over
          ? `${nameOf(active.id)} dropped at position ${positionOf(over.id)} of ${members.length}.`
          : `${nameOf(active.id)} returned to its position.`,
      onDragCancel: ({ active }) => `Reorder cancelled. ${nameOf(active.id)} returned.`,
    }),
    [members.length, nameOf, positionOf],
  )

  const screenReaderInstructions: ScreenReaderInstructions = useMemo(
    () => ({
      draggable:
        'Press space to pick up a Pokémon, arrow up and down to move it, space to drop, escape to cancel.',
    }),
    [],
  )

  function handleDragStart(event: DragStartEvent) {
    const data = event.active.data.current
    setDragging((data?.pokemon ?? data?.member ?? null) as PokemonSummary | TeamMember | null)
  }

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    setDragging(null)
    if (!over || !team) return

    const activeId = String(active.id)
    const overId = String(over.id)

    if (activeId.startsWith('member-')) {
      const from = members.findIndex((m) => `member-${m.pokemon_id}` === activeId)
      const to = members.findIndex((m) => `member-${m.pokemon_id}` === overId)
      if (from === -1 || to === -1 || from === to) return
      persist(arrayMove(members, from, to).map(toEntry))
      return
    }

    if (activeId.startsWith('catalog-') && overId.startsWith('slot-')) {
      const pokemon = active.data.current?.pokemon as PokemonSummary | undefined
      if (pokemon) addPokemon(pokemon)
    }
  }

  const draggingType =
    dragging && 'types' in dragging ? (dragging.types[0] as string | undefined) : undefined

  const panel = (
    <TeamPanel
      teams={teams.data ?? []}
      team={team}
      members={members}
      activeType={draggingType}
      onSelect={select}
      onRemove={removeMember}
    />
  )

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={() => setDragging(null)}
      // Droppable rects are cached, and the grid scrolls underneath a fixed
      // panel. Without continuous measuring the slots silently stop accepting
      // drops as soon as the grid moves.
      accessibility={{ announcements, screenReaderInstructions }}
      measuring={{ droppable: { strategy: MeasuringStrategy.Always } }}
      // Scoped to the grid. Left on the window, dragging near the panel edge
      // lurches the whole page.
      autoScroll={{ canScroll: (element) => element === gridRef.current }}
    >
      <div className="bg-background text-foreground flex h-svh flex-col overflow-hidden">
        <header className="border-border/60 flex shrink-0 items-center gap-3 border-b px-4 py-3">
          <h1 className="font-display text-sm font-semibold tracking-tight">Team Builder</h1>
          <span className="text-muted-foreground hidden text-xs sm:inline">
            Click + to add, drag slots to reorder
          </span>
          <div className="ml-auto flex items-center gap-2">
            <NotificationBell />
            <ThemeToggle />
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          {/* Only this scrolls. */}
          <div ref={gridRef} className="min-w-0 flex-1 overflow-y-auto overscroll-contain">
            <Catalog
              teamIds={members.map((member) => member.pokemon_id)}
              rosterFull={rosterFull}
              onAdd={addPokemon}
              scrollRef={gridRef}
            />
          </div>

          <TeamRail members={members} onExpand={() => setSheetOpen(true)} />

          <aside className="border-border hidden w-[340px] shrink-0 overflow-y-auto border-l lg:block">
            {teams.isError ? (
              <div className="p-3">
                <ErrorState
                  message="Could not load your teams."
                  onRetry={() => void teams.refetch()}
                />
              </div>
            ) : (
              panel
            )}
          </aside>
        </div>

        <TeamBar members={members} onExpand={() => setSheetOpen(true)} />
      </div>

      <TeamSheet open={sheetOpen} onClose={() => setSheetOpen(false)}>
        {panel}
      </TeamSheet>

      {/* Portalled to the body so the grid's overflow container cannot clip
          the card being dragged. */}
      {createPortal(
        <DragOverlay dropAnimation={{ duration: 180, easing: 'cubic-bezier(0.16,1,0.3,1)' }}>
          {dragging ? (
            <div
              className={cn(
                'cursor-grabbing',
                'stats' in dragging ? 'w-[180px] rotate-2 scale-[1.04]' : 'w-[300px]',
              )}
            >
              {'stats' in dragging ? (
                <CardBody pokemon={dragging} dragging />
              ) : (
                // Mirrors the row it was lifted from, so the drag reads as
                // picking that row up rather than swapping it for a token.
                <div
                  data-type={dragging.types[0]}
                  className="border-border flex rotate-1 scale-[1.02] items-center gap-2 rounded-[12px] border py-1.5 pr-3 pl-1.5 shadow-2xl"
                  style={{ background: 'color-mix(in oklch, var(--type) 7%, var(--card))' }}
                >
                  <GripVertical aria-hidden className="text-muted-foreground/50 size-3.5 shrink-0" />
                  <Sprite
                    src={dragging.sprite_url}
                    alt={dragging.name}
                    size="sm"
                    type={dragging.types[0]}
                  />
                  <div className="min-w-0">
                    <span className="font-display block truncate text-xs font-medium capitalize">
                      {dragging.name}
                    </span>
                    <TypeBadges types={dragging.types} className="mt-0.5" />
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </DragOverlay>,
        document.body,
      )}
    </DndContext>
  )
}
