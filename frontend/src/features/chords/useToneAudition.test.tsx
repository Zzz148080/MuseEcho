import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { pitchClassFrequency, useToneAudition } from './useToneAudition'

describe('useToneAudition', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('maps supported natural, sharp, flat, and double-sharp pitch classes', () => {
    expect(pitchClassFrequency('A', 4)).toBeCloseTo(440, 4)
    expect(pitchClassFrequency('Bb', 4)).toBeCloseTo(466.1638, 3)
    expect(pitchClassFrequency('G##', 4)).toBeCloseTo(440, 4)
    expect(pitchClassFrequency('H', 4)).toBeNull()
  })

  it('creates one short decaying tone only when audition is called', () => {
    const oscillator = {
      addEventListener: vi.fn(),
      connect: vi.fn(),
      frequency: { setValueAtTime: vi.fn() },
      start: vi.fn(),
      stop: vi.fn(),
      type: 'sine' as OscillatorType,
    }
    const gain = {
      connect: vi.fn(),
      gain: {
        exponentialRampToValueAtTime: vi.fn(),
        setValueAtTime: vi.fn(),
      },
    }
    const close = vi.fn().mockResolvedValue(undefined)
    class AudioContextDouble {
      currentTime = 2
      destination = {}
      state = 'running'
      close = close
      createGain = () => gain
      createOscillator = () => oscillator
      resume = vi.fn().mockResolvedValue(undefined)
    }
    vi.stubGlobal('AudioContext', AudioContextDouble)

    const { result, unmount } = renderHook(() => useToneAudition())
    expect(oscillator.start).not.toHaveBeenCalled()

    act(() => expect(result.current.audition('C')).toBe(true))

    expect(oscillator.frequency.setValueAtTime).toHaveBeenCalledWith(
      expect.closeTo(261.6256, 3),
      2,
    )
    expect(oscillator.start).toHaveBeenCalledWith(2)
    expect(oscillator.stop).toHaveBeenCalledWith(3.2)
    act(() => expect(result.current.audition('D', 5)).toBe(true))
    expect(oscillator.frequency.setValueAtTime).toHaveBeenLastCalledWith(
      expect.closeTo(587.3295, 3),
      2,
    )
    unmount()
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('reports an inline-capable fallback when Web Audio is unavailable', () => {
    vi.stubGlobal('AudioContext', undefined)
    const { result } = renderHook(() => useToneAudition())

    act(() => expect(result.current.audition('C')).toBe(false))

    expect(result.current.unavailable).toBe(true)
  })

  it('reports suspended-context resume rejection and releases that context', async () => {
    const oscillator = {
      addEventListener: vi.fn(),
      connect: vi.fn(),
      frequency: { setValueAtTime: vi.fn() },
      start: vi.fn(),
      stop: vi.fn(),
      type: 'sine' as OscillatorType,
    }
    const gain = {
      connect: vi.fn(),
      gain: {
        exponentialRampToValueAtTime: vi.fn(),
        setValueAtTime: vi.fn(),
      },
    }
    const close = vi.fn().mockResolvedValue(undefined)
    class SuspendedAudioContextDouble {
      currentTime = 0
      destination = {}
      state = 'suspended'
      close = close
      createGain = () => gain
      createOscillator = () => oscillator
      resume = vi.fn().mockRejectedValue(new Error('playback blocked'))
    }
    vi.stubGlobal('AudioContext', SuspendedAudioContextDouble)

    const { result } = renderHook(() => useToneAudition())

    act(() => expect(result.current.audition('C')).toBe(true))

    await waitFor(() => expect(result.current.unavailable).toBe(true))
    expect(close).toHaveBeenCalledTimes(1)
  })

  it('does not let an older resume rejection stop a newer audition context', async () => {
    const resumeAttempts: Array<{
      reject: (reason: Error) => void
      promise: Promise<void>
    }> = []
    const makeResumeAttempt = () => {
      let reject: (reason: Error) => void = () => undefined
      const promise = new Promise<void>((_resolve, rejectPromise) => {
        reject = rejectPromise
      })
      const attempt = { reject, promise }
      resumeAttempts.push(attempt)
      return promise
    }
    const oscillators = Array.from({ length: 3 }, () => ({
      addEventListener: vi.fn(),
      connect: vi.fn(),
      frequency: { setValueAtTime: vi.fn() },
      start: vi.fn(),
      stop: vi.fn(),
      type: 'sine' as OscillatorType,
    }))
    const closes = [vi.fn().mockResolvedValue(undefined), vi.fn()]
    let contextIndex = 0
    let oscillatorIndex = 0
    class AudioContextRaceDouble {
      currentTime = 0
      destination = {}
      index = contextIndex++
      state = this.index === 0 ? 'suspended' : 'running'
      close = closes[this.index]
      createGain = () => ({
        connect: vi.fn(),
        gain: {
          exponentialRampToValueAtTime: vi.fn(),
          setValueAtTime: vi.fn(),
        },
      })
      createOscillator = () => oscillators[oscillatorIndex++]
      resume = vi.fn(() => makeResumeAttempt())
    }
    vi.stubGlobal('AudioContext', AudioContextRaceDouble)

    const { result } = renderHook(() => useToneAudition())
    act(() => expect(result.current.audition('C')).toBe(true))
    act(() => expect(result.current.audition('E')).toBe(true))
    expect(resumeAttempts).toHaveLength(2)

    await act(async () => {
      resumeAttempts[1].reject(new Error('latest attempt blocked'))
      await resumeAttempts[1].promise.catch(() => undefined)
    })
    expect(result.current.unavailable).toBe(true)

    act(() => expect(result.current.audition('G')).toBe(true))
    expect(result.current.unavailable).toBe(false)
    expect(oscillators[2].stop).toHaveBeenCalledTimes(1)

    await act(async () => {
      resumeAttempts[0].reject(new Error('older attempt finished late'))
      await resumeAttempts[0].promise.catch(() => undefined)
    })

    expect(result.current.unavailable).toBe(false)
    expect(closes[1]).not.toHaveBeenCalled()
    expect(oscillators[2].stop).toHaveBeenCalledTimes(1)
  })
})
