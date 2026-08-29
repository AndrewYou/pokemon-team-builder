/**
 * Application root. The team builder proper will render here; for now it is a
 * placeholder so that `/` is never again occupied by a diagnostic page.
 */
export default function HomePage() {
  return (
    <main className="bg-background flex min-h-svh items-center justify-center p-6">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">Pokémon Team Builder</h1>
        <p className="text-muted-foreground mt-2 text-sm">
          Catalog and team builder coming next.
        </p>
      </div>
    </main>
  )
}
