import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { analysisId, fixtureResult } from '../../test/analysisFixture'
import { AnalysisWorkspace } from './AnalysisWorkspace'

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

    await user.click(screen.getByRole('button', { name: '返回结构地图' }))
    expect(screen.queryByRole('heading', { name: 'G 和弦' })).not.toBeInTheDocument()
    expect(chord).toHaveFocus()
    expect(loadResult).toHaveBeenCalledTimes(1)
  })

  it('clears chord detail before a remounted map can restore focus', async () => {
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
    await user.click(remountedChord)
    await user.click(screen.getByRole('button', { name: '返回结构地图' }))

    expect(remountedChord).toHaveFocus()
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
