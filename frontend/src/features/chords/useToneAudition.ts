import { useCallback, useEffect, useRef, useState } from 'react'

const NOTE_INDEX: Readonly<Record<string, number>> = {
  C: 0,
  D: 2,
  E: 4,
  F: 5,
  G: 7,
  A: 9,
  B: 11,
}

export function pitchClassFrequency(
  pitchClass: string,
  octave = 4,
): number | null {
  const match = /^([A-G])([#b]{0,2})$/.exec(pitchClass)
  if (!match || !Number.isInteger(octave)) return null
  const accidental = [...match[2]].reduce(
    (sum, mark) => sum + (mark === '#' ? 1 : -1),
    0,
  )
  const midi = 12 * (octave + 1) + NOTE_INDEX[match[1]] + accidental
  return 440 * 2 ** ((midi - 69) / 12)
}

export function useToneAudition() {
  const contextRef = useRef<AudioContext | null>(null)
  const activeRef = useRef<OscillatorNode[]>([])
  const [unavailable, setUnavailable] = useState(false)

  const stop = useCallback(() => {
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

  const audition = useCallback((pitchClass: string): boolean => {
    const frequency = pitchClassFrequency(pitchClass)
    const Context = window.AudioContext
    if (frequency === null || typeof Context !== 'function') {
      setUnavailable(true)
      return false
    }

    try {
      const context = contextRef.current ?? new Context()
      contextRef.current = context
      if (context.state === 'suspended') void context.resume()

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
  }, [])

  return { audition, unavailable, stop }
}
