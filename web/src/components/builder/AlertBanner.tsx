import { useAlerts, useDismissAlert } from '@/api/queries'

import { DisplayName, Sprite } from './primitives'

/**
 * Upstream changes affecting the current user's teams.
 *
 * Informational rather than alarming: a neutral surface with an accent left
 * border. These are "the data moved", not "something is broken", and styling
 * them as a warning would train the user to dismiss them unread.
 */
export function AlertBanner() {
  const alerts = useAlerts()
  const dismiss = useDismissAlert()

  if (alerts.isPending || alerts.isError) return null
  const groups = alerts.data?.groups ?? []
  if (groups.length === 0) return null

  return (
    <section
      aria-label="Changes affecting your teams"
      className="card-surface relative overflow-hidden p-3 pl-4"
    >
      <span aria-hidden className="bg-primary absolute inset-y-0 left-0 w-0.5" />
      <h2 className="font-display mb-2 text-xs font-medium">
        {alerts.data?.total_changes} change
        {alerts.data?.total_changes === 1 ? '' : 's'} upstream, affecting{' '}
        {alerts.data?.affected_pokemon} of your Pokémon
      </h2>
      <ul className="flex flex-col gap-2">
        {groups.map((group) => (
          <li key={group.pokemon_id} className="flex items-start gap-3">
            <Sprite
              src={group.sprite_url}
              alt={group.pokemon_name}
              size="sm"
              type={undefined}
            />
            <div className="min-w-0 flex-1">
              <p className="text-xs">
                <DisplayName name={group.pokemon_name} className="font-medium" />
                <span className="text-muted-foreground">
                  {' '}
                  on {group.affected_teams.map((team) => team.team_name).join(', ')}
                </span>
              </p>
              <ul className="mt-1 flex flex-col gap-1">
                {group.changes.map((change) => (
                  <li key={change.change_id} className="flex items-center gap-2">
                    <span className="text-muted-foreground flex-1 text-xs">
                      {change.message}
                    </span>
                    <button
                      type="button"
                      onClick={() => dismiss.mutate(change.change_id)}
                      className="text-muted-foreground hover:text-foreground hover:bg-muted rounded-[8px] px-2 py-0.5 text-[11px]"
                    >
                      Dismiss
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
