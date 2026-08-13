import { readFileSync } from 'node:fs'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'
import { vi } from 'vitest'
import { Button } from '../components/Button'
import { ConfidenceBadge } from '../components/ConfidenceBadge'
import { ErrorNotice } from '../components/ErrorNotice'
import { Panel } from '../components/Panel'
import { AnalysisPage } from './AnalysisPage'
import { fixtureResult } from '../test/analysisFixture'

const analysisId = '00000000-0000-4000-8000-000000000001'

describe('AnalysisPage', () => {
  it('provides a single labelled analysis workspace', () => {
    render(<AnalysisPage />)

    expect(
      screen.getByRole('main', { name: /museecho 音乐解析工作区/i }),
    ).toBeVisible()
  })

  it('uses listener-facing introduction copy instead of internal unknown markers', () => {
    render(<AnalysisPage />)

    expect(screen.getByText(/沿着时间线聆听节奏、能量与局部和声/)).toBeVisible()
    expect(screen.queryByText(/结果会明确标记为 unknown/)).not.toBeInTheDocument()
  })

  it('describes the honest empty workflow without inventing analysis facts', () => {
    render(<AnalysisPage />)

    expect(screen.getByRole('heading', { name: '开始解析' })).toBeVisible()
    expect(screen.getByRole('region', { name: '分析流程' })).toBeVisible()
    expect(screen.getByText(/尚未选择音频/)).toBeVisible()
    expect(screen.queryByText(/C major|情绪|乐器/i)).not.toBeInTheDocument()
  })

  it('stores only the analysis id in the URL and switches to real status', async () => {
    const user = userEvent.setup()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    const upload = vi.fn().mockResolvedValue({
      analysis_id: analysisId,
      stage: 'queued',
      progress: 0,
    })
    const loadStatus = vi.fn().mockResolvedValue({
      analysis_id: analysisId,
      status: 'queued',
      stage: 'queued',
      progress: 0,
      error_code: null,
      expires_at: '2026-08-10T00:00:00+00:00',
      pipeline_version: 'museecho-analysis-v1',
      source_kind: 'real',
    })
    window.history.replaceState(null, '', '/')
    render(
      <QueryClientProvider client={queryClient}>
        <AnalysisPage loadStatus={loadStatus} upload={upload} />
      </QueryClientProvider>,
    )

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    expect(await screen.findByText('等待分析')).toBeVisible()
    expect(new URL(window.location.href).searchParams.get('analysis')).toBe(analysisId)
    expect(window.location.href).not.toContain('token')
    expect(loadStatus).toHaveBeenCalledWith(analysisId)
    window.history.replaceState(null, '', '/')
  })

  it('restores status from a valid URL id after refresh', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    const loadStatus = vi.fn().mockResolvedValue({
      analysis_id: analysisId,
      status: 'complete',
      stage: 'complete',
      progress: 1,
      error_code: null,
      expires_at: '2026-08-10T00:00:00+00:00',
      pipeline_version: 'museecho-analysis-v1',
      source_kind: 'real',
    })
    const loadResult = vi.fn().mockResolvedValue(fixtureResult)
    window.history.replaceState(null, '', `/?analysis=${analysisId}`)
    render(
      <QueryClientProvider client={queryClient}>
        <AnalysisPage loadResult={loadResult} loadStatus={loadStatus} />
      </QueryClientProvider>,
    )

    expect(await screen.findByText('分析完成')).toBeVisible()
    expect(loadStatus).toHaveBeenCalledWith(analysisId)
    expect(await screen.findByRole('heading', { name: 'Music DNA' })).toBeVisible()
    expect(loadResult).toHaveBeenCalledWith(analysisId)
    window.history.replaceState(null, '', '/')
  })

  it('clears the analysis workspace and URL after confirmed deletion', async () => {
    const user = userEvent.setup()
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: 0 } },
    })
    const loadStatus = vi.fn().mockResolvedValue({
      analysis_id: analysisId,
      status: 'complete',
      stage: 'complete',
      progress: 1,
      error_code: null,
      expires_at: '2099-08-10T00:00:00+00:00',
      pipeline_version: 'museecho-analysis-v1',
      source_kind: 'real',
    })
    const removeAnalysis = vi.fn().mockResolvedValue(undefined)
    window.history.replaceState(null, '', `/?analysis=${analysisId}`)
    render(
      <QueryClientProvider client={queryClient}>
        <AnalysisPage
          loadResult={vi.fn().mockResolvedValue(fixtureResult)}
          loadStatus={loadStatus}
          removeAnalysis={removeAnalysis}
        />
      </QueryClientProvider>,
    )

    await screen.findByRole('heading', { name: 'Music DNA' })
    expect(screen.queryByRole('heading', { name: '片段问答' })).not.toBeInTheDocument()
    await user.click(screen.getByText('管理分析数据', { selector: 'summary' }))
    await user.click(screen.getByRole('checkbox', { name: /了解删除不可恢复/ }))
    await user.click(screen.getByRole('button', { name: '永久删除分析' }))

    expect(await screen.findByRole('heading', { name: '分析已永久删除' })).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Music DNA' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '播放器' })).not.toBeInTheDocument()
    expect(new URL(window.location.href).searchParams.has('analysis')).toBe(false)
    expect(removeAnalysis).toHaveBeenCalledWith(analysisId)
    window.history.replaceState(null, '', '/')
  })
})

describe('accessible foundation components', () => {
  it.each([
    ['high', '高置信'],
    ['medium', '中置信'],
    ['unknown', '证据不足'],
  ] as const)('labels %s confidence in text', (level, label) => {
    render(<ConfidenceBadge level={level} />)

    expect(screen.getByText(label)).toHaveAttribute('data-confidence', level)
  })

  it('announces a recoverable error and its next action', () => {
    render(
      <ErrorNotice
        title="无法读取音频"
        action="请检查文件格式后重新选择。"
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      '无法读取音频请检查文件格式后重新选择。',
    )
  })

  it('uses safe button defaults and unique labels for reusable panels', () => {
    render(
      <>
        <Button variant="secondary">检查</Button>
        <Panel title="证据"><p>第一组</p></Panel>
        <Panel title="证据"><p>第二组</p></Panel>
      </>,
    )

    expect(screen.getByRole('button', { name: '检查' })).toHaveAttribute(
      'type',
      'button',
    )
    const panels = screen.getAllByRole('region', { name: '证据' })
    expect(panels[0].getAttribute('aria-labelledby')).not.toBe(
      panels[1].getAttribute('aria-labelledby'),
    )
  })

  it('keeps focus visible and disables non-essential motion when requested', () => {
    const globalCss = readFileSync('src/styles/global.css', 'utf8')

    expect(globalCss).toMatch(/:focus-visible/)
    expect(globalCss).toMatch(/prefers-reduced-motion:\s*reduce/)
  })

  it('keeps the secondary data-management control in the single-column result flow', () => {
    const globalCss = readFileSync('src/styles/global.css', 'utf8')

    expect(globalCss).toMatch(
      /\.analysis-support\s*{[^}]*display:\s*block/s,
    )
  })

  it('keeps text and action colors at WCAG AA contrast', () => {
    const tokensCss = readFileSync('src/styles/tokens.css', 'utf8')
    const token = (name: string) => {
      const value = tokensCss.match(
        new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'),
      )?.[1]
      expect(value, `missing --${name} color token`).toBeDefined()
      return value as string
    }
    const luminance = (hex: string) => {
      const channels = [1, 3, 5].map((offset) =>
        Number.parseInt(hex.slice(offset, offset + 2), 16) / 255,
      )
      const [red, green, blue] = channels.map((channel) =>
        channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4,
      )
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort(
        (left, right) => right - left,
      )
      return (values[0] + 0.05) / (values[1] + 0.05)
    }

    expect(contrast(token('fg'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('fg-2'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('muted'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('surface'), token('accent'))).toBeGreaterThanOrEqual(
      4.5,
    )
    expect(contrast(token('surface'), token('danger'))).toBeGreaterThanOrEqual(
      4.5,
    )
  })
})
