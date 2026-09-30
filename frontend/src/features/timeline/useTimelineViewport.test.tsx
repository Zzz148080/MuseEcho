import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  anchoredScrollLeft,
  clampTimelineZoom,
  secondsToCanvasX,
  timelineCanvasWidth,
  useTimelineViewport,
} from './useTimelineViewport'

describe('useTimelineViewport', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('clamps zoom to quarter steps and derives one finite canvas coordinate', () => {
    expect(clampTimelineZoom(0.5)).toBe(1)
    expect(clampTimelineZoom(2.13)).toBe(2.25)
    expect(clampTimelineZoom(9)).toBe(4)
    expect(timelineCanvasWidth(800, 2.25)).toBe(1800)
    expect(secondsToCanvasX(30, 120, 1800)).toBe(450)
    expect(secondsToCanvasX(30, 0, 1800)).toBe(0)
  })

  it('centres the playhead while clamping naturally at both ends', () => {
    expect(anchoredScrollLeft(0, 120, 2400, 800)).toBe(0)
    expect(anchoredScrollLeft(60, 120, 2400, 800)).toBe(800)
    expect(anchoredScrollLeft(120, 120, 2400, 800)).toBe(1600)
    expect(anchoredScrollLeft(60, 0, 2400, 800)).toBe(0)
  })

  it('updates width and anchored scroll only inside its own viewport', () => {
    let notifyResize: (() => void) | undefined
    vi.stubGlobal(
      'ResizeObserver',
      class {
        constructor(callback: ResizeObserverCallback) {
          notifyResize = () => callback([], this as unknown as ResizeObserver)
        }
        observe() {}
        disconnect() {}
      },
    )

    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(800)

    function Harness() {
      const viewport = useTimelineViewport({ duration: 120, currentTime: 60 })
      return (
        <>
          <button onClick={() => viewport.setZoom(2)} type="button">
            放大
          </button>
          <output aria-label="画布宽度">{viewport.contentWidth}</output>
          <div data-testid="viewport" ref={viewport.viewportRef} />
        </>
      )
    }

    render(<Harness />)
    act(() => notifyResize?.())
    fireEvent.click(screen.getByRole('button', { name: '放大' }))

    const viewport = screen.getByTestId('viewport')
    expect(screen.getByLabelText('画布宽度')).toHaveTextContent('1600')
    expect(viewport.scrollLeft).toBe(400)
  })

  it('disables zoom geometry for a zero-duration result', () => {
    const { result } = renderHook(() =>
      useTimelineViewport({ duration: 0, currentTime: 0 }),
    )

    expect(result.current.disabled).toBe(true)
    expect(result.current.contentWidth).toBe(0)
  })
})
