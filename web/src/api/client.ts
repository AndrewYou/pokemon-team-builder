/**
 * The API client.
 *
 * Types come from src/api/schema.d.ts, generated from the server's OpenAPI
 * document by `npm run generate:api`. Nothing here restates a request or
 * response shape: if the server changes one, this stops compiling.
 */

import createClient, { type Middleware } from 'openapi-fetch'

import { getUserId } from '@/lib/identity'
import type { paths } from './schema'

export const API_URL: string = (
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
).replace(/\/+$/, '')

// Attaches the caller's identity to every request. Done as middleware rather
// than per call so a new endpoint cannot forget it and silently read an empty
// account.
const identity: Middleware = {
  async onRequest({ request }) {
    request.headers.set('X-User-Id', getUserId())
    return request
  },
}

export const api = createClient<paths>({ baseUrl: API_URL })
api.use(identity)

/** Narrow the generated response schemas to the shapes components consume. */
export type PokemonSummary =
  paths['/pokemon']['get']['responses'][200]['content']['application/json']['items'][number]
export type PokemonPage =
  paths['/pokemon']['get']['responses'][200]['content']['application/json']
export type TeamRead =
  paths['/teams']['get']['responses'][200]['content']['application/json'][number]
export type TeamMember = TeamRead['members'][number]
export type CounterTeamResponse =
  paths['/counter-team']['post']['responses'][200]['content']['application/json']
export type CounterPick = CounterTeamResponse['picks'][number]
export type CounterAnswer = CounterPick['answers'][number]
export type AlertsResponse =
  paths['/alerts']['get']['responses'][200]['content']['application/json']
export type AlertGroup = AlertsResponse['groups'][number]
export type TypeName = NonNullable<
  NonNullable<paths['/pokemon']['get']['parameters']['query']>['type']
>
