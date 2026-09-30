import { useEffect, type RefObject } from 'react'
import { timeToPercent } from './useTimeline'

/** Paint only the playhead and waveform, without rerendering the analysis tree. */
export function usePlaybackPaint(
  surface: RefObject<HTMLDivElement | null>,
  mediaRef: RefObject<HTMLAudioElement | null>,
  duration: number,
) {
  useEffect(() => {
    const media = mediaRef.current
    const element = surface.current
    if (!media || !element) return
    let frame = 0
    let buffering = false
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    const paint = () =>
      element.style.setProperty(
        '--playback',
        `${timeToPercent(media.currentTime, duration)}%`,
      )
    const stop = () => {
      cancelAnimationFrame(frame)
      frame = 0
    }
    const tick = () => {
      paint()
      frame = requestAnimationFrame(tick)
    }
    const reconcile = () => {
      stop()
      paint()
      if (
        !media.paused &&
        !media.ended &&
        !buffering &&
        !document.hidden &&
        !reduced?.matches
      )
        frame = requestAnimationFrame(tick)
    }
    const wait = () => {
      buffering = true
      reconcile()
    }
    const ready = () => {
      buffering = false
      reconcile()
    }
    media.addEventListener('playing', ready)
    media.addEventListener('waiting', wait)
    media.addEventListener('seeking', wait)
    media.addEventListener('seeked', ready)
    media.addEventListener('pause', reconcile)
    media.addEventListener('ended', reconcile)
    media.addEventListener('error', wait)
    media.addEventListener('timeupdate', paint)
    document.addEventListener('visibilitychange', reconcile)
    window.addEventListener('pageshow', reconcile)
    reduced?.addEventListener?.('change', reconcile)
    reconcile()
    return () => {
      stop()
      media.removeEventListener('playing', ready)
      media.removeEventListener('waiting', wait)
      media.removeEventListener('seeking', wait)
      media.removeEventListener('seeked', ready)
      media.removeEventListener('pause', reconcile)
      media.removeEventListener('ended', reconcile)
      media.removeEventListener('error', wait)
      media.removeEventListener('timeupdate', paint)
      document.removeEventListener('visibilitychange', reconcile)
      window.removeEventListener('pageshow', reconcile)
      reduced?.removeEventListener?.('change', reconcile)
    }
  }, [surface, mediaRef, duration])
}
