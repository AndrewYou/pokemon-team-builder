/**
 * Which team the panel is showing.
 *
 * One source of truth: the selected id. The heading, the slots, the
 * counter-team button and the alerts all derive from it, so no component holds
 * its own copy of a team's name and none of them can disagree.
 */

import { useCallback, useEffect, useState } from 'react'

import type { TeamRead } from '@/api/client'

const STORAGE_KEY = 'ptb.team-id'

function read(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? Number(raw) || null : null
  } catch {
    return null
  }
}

function write(id: number | null) {
  try {
    if (id === null) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, String(id))
  } catch {
    // Private browsing. The selection simply resets next visit.
  }
}

/** Most recently updated first -- the sensible fallback after a delete. */
function mostRecent(teams: TeamRead[]): TeamRead | undefined {
  return [...teams].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0]
}

export function useSelectedTeam(teams: TeamRead[] | undefined) {
  const [selectedId, setSelectedId] = useState<number | null>(read)

  const select = useCallback((id: number | null) => {
    setSelectedId(id)
    write(id)
  }, [])

  // A stored id can point at a team that has since been deleted, or at another
  // browser's team entirely. Resolve against what actually loaded.
  useEffect(() => {
    if (!teams || teams.length === 0) return
    if (selectedId !== null && teams.some((team) => team.id === selectedId)) return
    const fallback = mostRecent(teams)
    if (fallback) select(fallback.id)
  }, [teams, selectedId, select])

  const team = teams?.find((candidate) => candidate.id === selectedId) ?? null
  return { team, selectedId, select }
}
