import { useEffect, useState } from 'react'

export const MOBILE_WORKSPACE_QUERY = '(max-width: 599px)'
export const FULLSCREEN_CHORD_DETAIL_QUERY = '(max-width: 1023px)'

function matchesQuery(query: string): boolean {
  return typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function'
    ? window.matchMedia(query).matches
    : false
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => matchesQuery(query))

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mediaQuery = window.matchMedia(query)
    const updateMatches = (event: MediaQueryListEvent) =>
      setMatches(event.matches)

    setMatches(mediaQuery.matches)
    mediaQuery.addEventListener('change', updateMatches)
    return () => mediaQuery.removeEventListener('change', updateMatches)
  }, [query])

  return matches
}
