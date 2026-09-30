import { useRef } from 'react'
import { fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { usePlaybackPaint } from './usePlaybackPaint'

function Harness() {
  const media = useRef<HTMLAudioElement>(null)
  const surface = useRef<HTMLDivElement>(null)
  usePlaybackPaint(surface, media, 12)
  return (
    <>
      <audio ref={media} />
      <div ref={surface} data-testid="paint" />
    </>
  )
}

afterEach(() => vi.restoreAllMocks())

describe('playback painting lifecycle', () => {
  it('paints real time and cancels animation while waiting, paused, hidden and unmounted', () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame').mockReturnValue(25)
    const cancel = vi.spyOn(window, 'cancelAnimationFrame')
    const { container, unmount } = render(<Harness />)
    const media = container.querySelector('audio')!
    const surface = container.querySelector('div')!
    Object.defineProperty(media, 'paused', { value: false, configurable: true })
    Object.defineProperty(document, 'hidden', {
      value: false,
      configurable: true,
    })
    media.currentTime = 3
    fireEvent.playing(media)
    expect(surface.style.getPropertyValue('--playback')).toBe('25%')
    expect(raf).toHaveBeenCalledOnce()
    fireEvent.waiting(media)
    expect(cancel).toHaveBeenCalledWith(25)
    expect(raf).toHaveBeenCalledOnce()
    fireEvent.playing(media)
    Object.defineProperty(document, 'hidden', {
      value: true,
      configurable: true,
    })
    fireEvent(document, new Event('visibilitychange'))
    expect(raf).toHaveBeenCalledTimes(2)
    Object.defineProperty(document, 'hidden', {
      value: false,
      configurable: true,
    })
    Object.defineProperty(media, 'paused', { value: true, configurable: true })
    fireEvent.pause(media)
    unmount()
    fireEvent.playing(media)
    expect(raf).toHaveBeenCalledTimes(2)
    Reflect.deleteProperty(document, 'hidden')
  })

  it('uses discrete media updates when reduced motion is requested', () => {
    const raf = vi.spyOn(window, 'requestAnimationFrame')
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    )
    const { container, unmount } = render(<Harness />)
    const media = container.querySelector('audio')!
    Object.defineProperty(media, 'paused', { value: false })
    media.currentTime = 6
    fireEvent.playing(media)
    expect(raf).not.toHaveBeenCalled()
    expect(
      container.querySelector('div')!.style.getPropertyValue('--playback'),
    ).toBe('50%')
    unmount()
    vi.unstubAllGlobals()
  })
})
