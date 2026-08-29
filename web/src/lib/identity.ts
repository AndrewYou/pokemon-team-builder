/**
 * Client identity.
 *
 * There is no login. The API issues an opaque UUID and whoever presents it
 * owns the teams created under it, so the only job here is to mint one once
 * and keep sending the same one.
 */

const STORAGE_KEY = 'ptb.user-id'

function mint(): string {
  // randomUUID needs a secure context, which localhost and https both are.
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  // Fallback for an insecure origin, e.g. a LAN IP during testing.
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (c) =>
    (
      Number(c) ^
      (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (Number(c) / 4)))
    ).toString(16),
  )
}

export function getUserId(): string {
  try {
    const existing = localStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const created = mint()
    localStorage.setItem(STORAGE_KEY, created)
    return created
  } catch {
    // Private browsing can throw on access. A per-session identity is worse
    // than a persisted one but better than crashing on load.
    return mint()
  }
}
