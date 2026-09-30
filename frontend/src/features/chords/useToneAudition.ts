import { useCallback, useEffect, useRef, useState } from 'react'

import { noteValue } from './musicNotation'

export function pitchClassFrequency(
  pitchClass: string,
  octave = 4,
): number | null {
  const value = noteValue(pitchClass)
  if (value === null || !Number.isInteger(octave)) return null
  const midi = 12 * (octave + 1) + value
  return 440 * 2 ** ((midi - 69) / 12)
}

export function useToneAudition() {
  const contextRef = useRef<AudioContext | null>(null)
  const activeRef = useRef<OscillatorNode[]>([])
  const auditionAttemptRef = useRef(0)
  const [unavailable, setUnavailable] = useState(false)

  const stop = useCallback(() => {
    auditionAttemptRef.current += 1
    activeRef.current.forEach((oscillator) => {
      try {
        oscillator.stop()
      } catch {
        // A scheduled oscillator may already have ended.
      }
    })
    activeRef.current = []
    const context = contextRef.current
    contextRef.current = null
    if (context) void context.close()
  }, [])

  useEffect(() => stop, [stop])

  const audition = useCallback(
    (pitchClass: string, octave = 4): boolean => {
      const frequency = pitchClassFrequency(pitchClass, octave)
      const Context = window.AudioContext
      if (frequency === null || typeof Context !== 'function') {
        setUnavailable(true)
        return false
      }
      const auditionAttempt = ++auditionAttemptRef.current

      try {
        const context = contextRef.current ?? new Context()
        contextRef.current = context
        if (context.state === 'suspended') {
          void context.resume().catch(() => {
            if (
              contextRef.current !== context ||
              auditionAttemptRef.current !== auditionAttempt
            ) {
              return
            }
            stop()
            setUnavailable(true)
          })
        }

        const oscillator = context.createOscillator()
        const gain = context.createGain()
        const now = context.currentTime
        oscillator.type = 'triangle'
        oscillator.frequency.setValueAtTime(frequency, now)
        gain.gain.setValueAtTime(0.0001, now)
        gain.gain.exponentialRampToValueAtTime(0.26, now + 0.02)
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 1.2)
        oscillator.connect(gain)
        gain.connect(context.destination)
        oscillator.start(now)
        oscillator.stop(now + 1.2)
        activeRef.current.push(oscillator)
        oscillator.addEventListener(
          'ended',
          () => {
            activeRef.current = activeRef.current.filter(
              (active) => active !== oscillator,
            )
          },
          { once: true },
        )
        setUnavailable(false)
        return true
      } catch {
        setUnavailable(true)
        return false
      }
    },
    [stop],
  )

  return { audition, unavailable, stop }
}
