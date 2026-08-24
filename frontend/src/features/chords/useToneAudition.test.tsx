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
})
