import { useEffect, useState } from 'react'

const STORAGE_KEY = 'ptb.theme'
type Theme = 'dark' | 'light'

/** Dark by default; the choice is remembered. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem(STORAGE_KEY) as Theme) ?? 'dark'
    } catch {
      return 'dark'
    }
  })

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark')
    try {
      localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // Private browsing; the theme simply resets next visit.
    }
  }, [theme])

  return (
    <button
      type="button"
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
      className="border-border bg-card hover:bg-muted grid size-8 place-items-center rounded-[8px] border text-xs"
    >
      {theme === 'dark' ? '☾' : '☀'}
    </button>
  )
}
