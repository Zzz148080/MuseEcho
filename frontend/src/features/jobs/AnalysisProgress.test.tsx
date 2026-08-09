import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { AnalysisStatus } from '../../api/types'
import { AnalysisProgress, statusPollInterval } from './AnalysisProgress'

const analysisId = '00000000-0000-4000-8000-000000000001'

function status(overrides: Partial<AnalysisStatus> = {}): AnalysisStatus {
  return {
    analysis_id: analysisId,
    status: 'tonality',
    stage: 'tonality',
    progress: 0.5,
    error_code: null,
    expires_at: '2026-08-10T00:00:00+00:00',
    pipeline_version: 'museecho-analysis-v1',
    source_kind: 'real',
    ...overrides,
  }
}

function renderProgress(loadStatus: () => Promise<AnalysisStatus>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalysisProgress analysisId={analysisId} loadStatus={loadStatus} />
    </QueryClientProvider>,
  )
}

describe('AnalysisProgress', () => {
  it('shows the real server stage and progress without inventing remaining time', async () => {
    renderProgress(vi.fn().mockResolvedValue(status()))

    expect(await screen.findByText('分析调性')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: /分析进度/ })).toHaveValue(50)
    expect(screen.getByText(/服务端未提供可靠估算/)).toBeVisible()
    expect(screen.getByText('真实上传')).toBeVisible()
  })

  it('stops status polling for every terminal state', () => {
    expect(statusPollInterval(undefined)).toBe(1500)
    expect(statusPollInterval(undefined, true)).toBe(false)
    expect(statusPollInterval(status({ stage: 'queued', status: 'queued' }))).toBe(1500)

    for (const stage of ['complete', 'failed', 'expired', 'deleted'] as const) {
      expect(statusPollInterval(status({ stage, status: stage }))).toBe(false)
    }
  })

  it('announces a status failure and offers an accessible retry', async () => {
    const user = userEvent.setup()
    const loadStatus = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(404, 'not_found', 'Not Found'))
      .mockResolvedValueOnce(status({ stage: 'queued', status: 'queued', progress: 0 }))
    renderProgress(loadStatus)

    expect(await screen.findByRole('alert')).toHaveTextContent(/无法读取分析状态/)
    await user.click(screen.getByRole('button', { name: /重试/ }))

    expect(await screen.findByText('等待分析')).toBeVisible()
    expect(loadStatus).toHaveBeenCalledTimes(2)
  })

  it('announces a terminal analysis failure with a friendly stable code', async () => {
    renderProgress(
      vi.fn().mockResolvedValue(
        status({
          stage: 'failed',
          status: 'failed',
          error_code: 'analysis_input_unavailable',
        }),
      ),
    )

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /加密音频输入不可用.*analysis_input_unavailable/,
    )
  })
})
