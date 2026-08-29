import { useCallback, useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { API_URL, fetchHealth, type HealthResponse } from '@/lib/api'

type Status =
  | { state: 'loading' }
  | { state: 'ready'; health: HealthResponse }
  | { state: 'error'; message: string }

function StatusBadge({ status }: { status: Status }) {
  if (status.state === 'loading') return <Badge variant="secondary">checking…</Badge>
  if (status.state === 'error') return <Badge variant="destructive">unreachable</Badge>
  return status.health.ok ? (
    <Badge className="bg-emerald-600 text-white hover:bg-emerald-600">healthy</Badge>
  ) : (
    <Badge variant="destructive">degraded</Badge>
  )
}

/** A labelled key/value row. */
function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-2 last:border-b-0">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="font-mono text-sm break-all">{children}</span>
    </div>
  )
}

export default function HealthPage() {
  const [status, setStatus] = useState<Status>({ state: 'loading' })

  const check = useCallback((signal?: AbortSignal) => {
    setStatus({ state: 'loading' })
    fetchHealth(signal)
      .then((health) => setStatus({ state: 'ready', health }))
      .catch((error: unknown) => {
        if (signal?.aborted) return
        setStatus({ state: 'error', message: error instanceof Error ? error.message : String(error) })
      })
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    check(controller.signal)
    return () => controller.abort()
  }, [check])

  return (
    <main className="bg-background flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <CardTitle>Pokémon Team Builder</CardTitle>
            <StatusBadge status={status} />
          </div>
          <CardDescription>
            Connectivity check between the frontend and the API. Not part of the app itself.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <Row label="API">{API_URL}</Row>
            <Row label="ok">
              {status.state === 'ready' ? String(status.health.ok) : '—'}
            </Row>
            <Row label="db">
              {status.state === 'ready' ? (
                <span className={status.health.ok ? 'text-emerald-600' : 'text-destructive'}>
                  {status.health.db}
                </span>
              ) : status.state === 'error' ? (
                <span className="text-destructive">{status.message}</span>
              ) : (
                '—'
              )}
            </Row>
          </div>
          <Button
            onClick={() => check()}
            disabled={status.state === 'loading'}
            className="w-full"
            variant="secondary"
          >
            {status.state === 'loading' ? 'Checking…' : 'Re-check'}
          </Button>
        </CardContent>
      </Card>
    </main>
  )
}
