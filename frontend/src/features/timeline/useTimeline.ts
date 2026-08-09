import { useCallback, useRef, useState, type RefObject } from 'react'

export interface TimeSelection {
  start: number
  end: number
}

export interface TimelineController {
  currentTime: number
  duration: number
  mediaRef: RefObject<HTMLAudioElement | null>
  selection: TimeSelection | null
  clearSelection: () => void
  seek: (seconds: number) => void
  select: (start: number, end: number) => void
  syncFromMedia: () => void
}

export function useTimeline(duration: number): TimelineController {
  const safeDuration = finiteClamp(duration, 0, Number.MAX_SAFE_INTEGER)
  const mediaRef = useRef<HTMLAudioElement>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [selection, setSelection] = useState<TimeSelection | null>(null)

  const seek = useCallback(
    (seconds: number) => {
      const next = finiteClamp(seconds, 0, safeDuration)
      if (mediaRef.current) mediaRef.current.currentTime = next
      setCurrentTime(next)
    },
    [safeDuration],
  )

  const syncFromMedia = useCallback(() => {
    if (mediaRef.current) {
      setCurrentTime(finiteClamp(mediaRef.current.currentTime, 0, safeDuration))
    }
  }, [safeDuration])

  const select = useCallback(
    (start: number, end: number) => {
      const first = finiteClamp(Math.min(start, end), 0, safeDuration)
      const last = finiteClamp(Math.max(start, end), 0, safeDuration)
      setSelection(last > first ? { start: first, end: last } : null)
    },
    [safeDuration],
  )

  return {
    currentTime,
    duration: safeDuration,
    mediaRef,
    selection,
    clearSelection: () => setSelection(null),
    seek,
    select,
    syncFromMedia,
  }
}

export function finiteClamp(value: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(value)) return minimum
  return Math.min(maximum, Math.max(minimum, value))
}

export function timeToPercent(seconds: number, duration: number): number {
  if (!Number.isFinite(duration) || duration <= 0) return 0
  return finiteClamp(seconds / duration, 0, 1) * 100
}
