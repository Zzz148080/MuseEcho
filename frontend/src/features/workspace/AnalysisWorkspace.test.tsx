import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
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
  it('loads the persisted result and exposes the synchronized evidence workspace', async () => {
    const { loadResult } = renderWorkspace()

    expect(await screen.findByRole('heading', { name: 'Music DNA' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '播放器' })).toBeVisible()
    expect(screen.getByRole('heading', { name: '结构地图' })).toBeVisible()
    expect(loadResult).toHaveBeenCalledWith(analysisId)
  })

  it('opens persisted theory when a chord seeks the shared media element', async () => {
    const user = userEvent.setup()
    const { container } = renderWorkspace()

    await screen.findByRole('heading', { name: 'Music DNA' })
    await user.click(screen.getByRole('button', { name: /和弦 G/ }))

    expect(container.querySelector('audio')?.currentTime).toBe(8)
    expect(screen.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
    expect(screen.getByText(/deterministic-triad-theory-v1/)).toBeVisible()
  })

  it('uses an explanation citation to seek and select the shared timeline', async () => {
    const user = userEvent.setup()
    const citedEvidence = {
      id: '00000000-0000-4000-8000-000000000031',
      kind: 'chord' as const,
      start_seconds: 8,
      end_seconds: 12,
      value: { symbol: 'G' },
      confidence: 0.89,
      algorithm: 'chords-v1',
      eligible_for_llm: true,
    }
    const result = { ...fixtureResult, evidence: [citedEvidence] }
    const ask = vi.fn().mockResolvedValue({
      mode: 'fallback',
      text: '确定性解释。',
      evidence_ids: [citedEvidence.id],
    })
    const loadResult = vi.fn().mockResolvedValue(result)
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <AnalysisWorkspace
          analysisId={analysisId}
          ask={ask}
          loadResult={loadResult}
        />
      </QueryClientProvider>,
    )

    await screen.findByRole('heading', { name: 'Music DNA' })
    fireEvent.change(screen.getByRole('slider', { name: '片段开始' }), {
      target: { value: '8' },
    })
    await user.type(screen.getByLabelText('问题'), '为什么是 G？')
    await user.click(screen.getByRole('button', { name: '解释片段' }))
    await user.click(await screen.findByRole('link', { name: /证据.*和弦/ }))

    expect(container.querySelector('audio')?.currentTime).toBe(8)
    expect(screen.getByTestId('selection')).toHaveAttribute('data-start', '8')
    expect(screen.getByTestId('selection')).toHaveAttribute('data-end', '12')
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
