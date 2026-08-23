import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { analysisId, fixtureResult } from '../../test/analysisFixture'
import { AnalysisWorkspace } from './AnalysisWorkspace'

afterEach(() => {
  vi.unstubAllGlobals()
})

function setMobileViewport(matches: boolean) {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      addEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: query === '(max-width: 599px)' && matches,
      media: query,
      onchange: null,
      removeEventListener: vi.fn(),
    })),
  )
}

function renderWorkspace(loadResult = vi.fn().mockResolvedValue(fixtureResult)) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return {
    loadResult,
    ...render(
      <QueryClientProvider client={queryClient}>
        <AnalysisWorkspace analysisId={analysisId} loadResult={loadResult} />
      </QueryClientProvider>,
    ),
  }
}

function renderWorkspaceInAppShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <div className="app-shell">
      <button type="button">新的分析</button>
      <QueryClientProvider client={queryClient}>
        <AnalysisWorkspace
          analysisId={analysisId}
          loadResult={vi.fn().mockResolvedValue(fixtureResult)}
        />
      </QueryClientProvider>
    </div>,
  )
}

describe('AnalysisWorkspace', () => {
  it('loads one result and initially exposes only the overview', async () => {
    const { loadResult } = renderWorkspace()

    expect(await screen.findByRole('heading', { name: 'Music DNA' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '播放器' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: '结构地图' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '深入分析' })).not.toBeInTheDocument()
    expect(loadResult).toHaveBeenCalledTimes(1)
  })

  it('switches views without refetching and opens chord theory as a returnable detail', async () => {
    const user = userEvent.setup()
    const { container, loadResult } = renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    const chord = screen.getByRole('button', { name: /和弦 G/ })
    await user.click(chord)

    expect(container.querySelector('audio')?.currentTime).toBe(8)
    expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
    expect(screen.getByRole('button', { name: '返回结构地图' })).toBeVisible()
    expect(screen.getByRole('button', { name: '返回结构地图' })).toHaveFocus()

    await user.click(screen.getByRole('button', { name: '返回结构地图' }))
    expect(screen.queryByRole('heading', { name: 'G 和弦' })).not.toBeInTheDocument()
    expect(chord).toHaveFocus()
    expect(chord).toHaveAttribute('aria-pressed', 'true')
    expect(loadResult).toHaveBeenCalledTimes(1)
  })

  it('preserves selection across view navigation and restores focus only to a freshly opened trigger', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    await user.click(screen.getByRole('button', { name: /和弦 G/ }))
    expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: /歌曲概览/ }))
    await user.click(screen.getByRole('button', { name: /结构地图/ }))

    expect(screen.queryByRole('heading', { name: 'G 和弦' })).not.toBeInTheDocument()

    const remountedChord = screen.getByRole('button', { name: /和弦 G/ })
    expect(remountedChord).toHaveAttribute('aria-pressed', 'true')
    await user.click(remountedChord)
    expect(screen.getByRole('button', { name: '返回结构地图' })).toHaveFocus()
    await user.click(screen.getByRole('button', { name: '返回结构地图' }))

    expect(remountedChord).toHaveFocus()
  })

  it('uses a focused modal detail and makes the covered workspace inert only on mobile', async () => {
    setMobileViewport(true)
    const user = userEvent.setup()
    const { container } = renderWorkspaceInAppShell()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    const chord = screen.getByRole('button', { name: /和弦 G/ })
    await user.click(chord)

    const detail = screen.getByRole('dialog', { name: 'G 和弦' })
    expect(detail).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: '返回结构地图' })).toHaveFocus()
    expect(container.querySelector('.app-shell')).toHaveAttribute('inert')
    expect(container.querySelector('.app-shell')).toHaveAttribute('aria-hidden', 'true')

    await user.click(screen.getByRole('button', { name: '返回结构地图' }))

    expect(chord).toHaveFocus()
    expect(chord).toHaveAttribute('aria-pressed', 'true')
    expect(container.querySelector('.app-shell')).not.toHaveAttribute('inert')
  })

  it('keeps the desktop side detail non-modal while moving focus into it', async () => {
    setMobileViewport(false)
    const user = userEvent.setup()
    const { container } = renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    await user.click(screen.getByRole('button', { name: /和弦 G/ }))

    const detail = screen.getByRole('complementary', { name: '当前和弦详情' })
    expect(detail).not.toHaveAttribute('aria-modal')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回结构地图' })).toHaveFocus()
    expect(container.querySelector('.music-workspace')).not.toHaveAttribute('inert')
  })

  it('clears the preserved chord only through an explicit deselection action', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    const chord = screen.getByRole('button', { name: /和弦 G/ })
    await user.click(chord)
    await user.click(screen.getByRole('button', { name: '返回结构地图' }))

    expect(chord).toHaveAttribute('aria-pressed', 'true')
    await user.click(screen.getByRole('button', { name: '清除和弦选择' }))
    expect(chord).toHaveAttribute('aria-pressed', 'false')
  })

  it('clears workspace selection state when the analysis identity changes', async () => {
    const nextAnalysisId = '00000000-0000-4000-8000-000000000002'
    const nextResult = {
      ...fixtureResult,
      analysis_id: nextAnalysisId,
      chords: fixtureResult.chords.map((chord, index) => ({
        ...chord,
        id: `00000000-0000-4000-8000-${String(index + 31).padStart(12, '0')}`,
      })),
    }
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    })
    queryClient.setQueryData(['analysis-result', analysisId], fixtureResult)
    queryClient.setQueryData(['analysis-result', nextAnalysisId], nextResult)
    const loadResult = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <AnalysisWorkspace analysisId={analysisId} loadResult={loadResult} />
      </QueryClientProvider>,
    )

    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    await user.click(screen.getByRole('button', { name: /和弦 G/ }))
    await user.click(screen.getByRole('button', { name: '返回结构地图' }))
    expect(screen.getByRole('button', { name: '清除和弦选择' })).toBeVisible()

    rerender(
      <QueryClientProvider client={queryClient}>
        <AnalysisWorkspace analysisId={nextAnalysisId} loadResult={loadResult} />
      </QueryClientProvider>,
    )
    await user.click(screen.getByRole('button', { name: /结构地图/ }))

    expect(screen.queryByRole('button', { name: '清除和弦选择' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /和弦 G/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(loadResult).not.toHaveBeenCalled()
  })

  it('keeps secondary data management outside the primary result views', async () => {
    const user = userEvent.setup()
    renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /结构地图/ }))

    expect(screen.getByRole('group', { name: '片段选择轨道' })).toBeVisible()
    expect(screen.getByRole('group', { name: '片段选择' })).toBeVisible()
    expect(screen.getByRole('group', { name: '管理分析数据' })).not.toHaveAttribute('open')
  })

  it('announces result failures and retries only on user action', async () => {
    const user = userEvent.setup()
    const loadResult = vi
      .fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(fixtureResult)
    renderWorkspace(loadResult)

    expect(await screen.findByRole('alert')).toHaveTextContent(/无法读取分析结果/)
    expect(loadResult).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: /重试读取结果/ }))

    expect(await screen.findByRole('heading', { name: 'Music DNA' })).toBeVisible()
    expect(loadResult).toHaveBeenCalledTimes(2)
  })
})
