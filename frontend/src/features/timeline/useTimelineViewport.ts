import {
  useCallback,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from 'react'
import { finiteClamp } from './useTimeline'

export const TIMELINE_MIN_ZOOM = 1
export const TIMELINE_MAX_ZOOM = 4
export const TIMELINE_ZOOM_STEP = 0.25

export interface TimelineViewportController {
  zoom: number
  setZoom: (zoom: number) => void
  viewportRef: RefObject<HTMLDivElement | null>
  contentWidth: number
  disabled: boolean
}

export function clampTimelineZoom(value: number): number {
  const stepped = Math.round(value / TIMELINE_ZOOM_STEP) * TIMELINE_ZOOM_STEP
  return finiteClamp(stepped, TIMELINE_MIN_ZOOM, TIMELINE_MAX_ZOOM)
}

export function timelineCanvasWidth(viewportWidth: number, zoom: number): number {
  if (!Number.isFinite(viewportWidth) || viewportWidth <= 0) return 0
  return viewportWidth * clampTimelineZoom(zoom)
}

export function secondsToCanvasX(
  seconds: number,
  duration: number,
  contentWidth: number,
): number {
  if (!Number.isFinite(duration) || duration <= 0 || contentWidth <= 0) return 0
  return finiteClamp(seconds / duration, 0, 1) * contentWidth
}

export function anchoredScrollLeft(
  currentTime: number,
  duration: number,
  contentWidth: number,
  viewportWidth: number,
): number {
  if (
    !Number.isFinite(duration) ||
    duration <= 0 ||
    viewportWidth <= 0 ||
    contentWidth <= viewportWidth
  ) {
    return 0
  }
  return finiteClamp(
    secondsToCanvasX(currentTime, duration, contentWidth) - viewportWidth / 2,
    0,
    contentWidth - viewportWidth,
  )
}

export function useTimelineViewport({
  duration,
  currentTime,
}: {
  duration: number
  currentTime: number
}): TimelineViewportController {
  const viewportRef = useRef<HTMLDivElement>(null)
  const [viewportWidth, setViewportWidth] = useState(0)
  const [zoom, setZoomState] = useState(TIMELINE_MIN_ZOOM)
  const pendingAnchor = useRef(false)
  const hasDuration = Number.isFinite(duration) && duration > 0
  const contentWidth = hasDuration
    ? timelineCanvasWidth(viewportWidth, zoom)
    : 0
  const disabled = !hasDuration || viewportWidth <= 0

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    const measure = () => setViewportWidth(viewport.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [])

  useLayoutEffect(() => {
    const viewport = viewportRef.current
    if (!pendingAnchor.current || !viewport) return
    pendingAnchor.current = false
    viewport.scrollLeft = anchoredScrollLeft(
      currentTime,
      duration,
      contentWidth,
      viewportWidth,
    )
  }, [contentWidth, currentTime, duration, viewportWidth])

  const setZoom = useCallback((next: number) => {
    pendingAnchor.current = true
    setZoomState(clampTimelineZoom(next))
  }, [])

  return { zoom, setZoom, viewportRef, contentWidth, disabled }
}
