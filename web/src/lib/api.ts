/**
 * Minimal health client.
 *
 * NOTE: CLAUDE.md mandates a generated OpenAPI client and TanStack Query for
 * server state. Both are deliberately deferred until the first real endpoint
 * exists -- this file is here only to prove the deploy pipeline end to end.
 */

export interface HealthResponse {
  ok: boolean
  db: string
}

/** Base URL of the API, without a trailing slash. */
export const API_URL: string = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '')

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_URL}/health`, { signal })
  if (!response.ok) {
    throw new Error(`API returned ${response.status} ${response.statusText}`)
  }
  return (await response.json()) as HealthResponse
}
