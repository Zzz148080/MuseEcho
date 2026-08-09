import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { EvidenceResult } from '../../api/types'
import { analysisId } from '../../test/analysisFixture'
import { QuestionPanel } from './QuestionPanel'

const evidence: EvidenceResult = {
  id: '00000000-0000-4000-8000-000000000031',
  kind: 'chord',
  start_seconds: 8,
  end_seconds: 12,
  value: { symbol: 'G' },
  confidence: 0.89,
  algorithm: 'chords-v1',
  eligible_for_llm: true,
}

describe('QuestionPanel', () => {
  it('renders fallback mode and cited evidence', async () => {
    const user = userEvent.setup()
    const ask = vi.fn().mockResolvedValue({
      mode: 'fallback',
      text: '确定性回退解释：这里只复述通过门控的和弦证据。',
      evidence_ids: [evidence.id],
    })
    render(
      <QuestionPanel
        analysisId={analysisId}
        ask={ask}
        evidence={[evidence]}
        onEvidenceSelect={vi.fn()}
        selection={{ start: 8, end: 12 }}
      />,
    )

    await user.type(screen.getByLabelText('问题'), '为什么这里有张力？')
    await user.click(screen.getByRole('button', { name: '解释片段' }))

    expect(await screen.findByText('确定性回退')).toBeVisible()
    expect(screen.getByRole('status')).toHaveTextContent(/只复述通过门控的和弦证据/)
    expect(screen.getByText(/只复述通过门控的和弦证据/)).toBeVisible()
    expect(screen.getByRole('link', { name: /证据.*和弦/ })).toBeVisible()
    expect(ask).toHaveBeenCalledWith(analysisId, {
      question: '为什么这里有张力？',
      start_seconds: 8,
      end_seconds: 12,
    })
  })

  it('selects cited evidence and brings the shared timeline into view', async () => {
    const user = userEvent.setup()
    const onEvidenceSelect = vi.fn()
    const scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    })
    render(
      <>
        <h2 id="timeline-title">时间轴</h2>
        <QuestionPanel
          analysisId={analysisId}
          ask={vi.fn().mockResolvedValue({
            mode: 'llm',
            text: '这段解释只引用已通过门控的证据。',
            evidence_ids: [evidence.id],
          })}
          evidence={[evidence]}
          onEvidenceSelect={onEvidenceSelect}
          selection={{ start: 8, end: 12 }}
        />
      </>,
    )

    await user.type(screen.getByLabelText('问题'), '定位证据')
    await user.click(screen.getByRole('button', { name: '解释片段' }))
    await user.click(await screen.findByRole('link', { name: /证据.*和弦/ }))

    expect(onEvidenceSelect).toHaveBeenCalledWith(evidence)
    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'start',
    })
  })

  it('blocks a missing or overlong selection before sending', async () => {
    const user = userEvent.setup()
    const ask = vi.fn()
    const { rerender } = render(
      <QuestionPanel
        analysisId={analysisId}
        ask={ask}
        evidence={[]}
        onEvidenceSelect={vi.fn()}
        selection={null}
      />,
    )

    await user.type(screen.getByLabelText('问题'), '解释这一段')
    expect(screen.getByRole('button', { name: '解释片段' })).toBeDisabled()
    expect(screen.getByText(/请先在结构地图选择片段/)).toBeVisible()

    rerender(
      <QuestionPanel
        analysisId={analysisId}
        ask={ask}
        evidence={[]}
        onEvidenceSelect={vi.fn()}
        selection={{ start: 0, end: 121 }}
      />,
    )
    expect(screen.getByRole('button', { name: '解释片段' })).toBeDisabled()
    expect(screen.getByText(/不能超过 2 分钟/)).toBeVisible()
    expect(ask).not.toHaveBeenCalled()
  })

  it('shows a stable rate-limit error and retries only after user action', async () => {
    const user = userEvent.setup()
    const ask = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(429, 'explanation_rate_limited'))
      .mockResolvedValueOnce({
        mode: 'fallback',
        text: '重试后的确定性解释。',
        evidence_ids: [],
      })
    render(
      <QuestionPanel
        analysisId={analysisId}
        ask={ask}
        evidence={[]}
        onEvidenceSelect={vi.fn()}
        selection={{ start: 1, end: 3 }}
      />,
    )

    await user.type(screen.getByLabelText('问题'), '这里发生了什么？')
    await user.click(screen.getByRole('button', { name: '解释片段' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/请求过于频繁.*一分钟/)
    expect(ask).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: '重新解释片段' }))
    expect(await screen.findByText('重试后的确定性解释。')).toBeVisible()
    expect(ask).toHaveBeenCalledTimes(2)
  })

  it('does not expose an Evidence item that is ineligible for LLM use', async () => {
    const user = userEvent.setup()
    const ineligible = { ...evidence, eligible_for_llm: false }
    render(
      <QuestionPanel
        analysisId={analysisId}
        ask={vi.fn().mockResolvedValue({
          mode: 'fallback',
          text: '没有通过门控的证据。',
          evidence_ids: [ineligible.id],
        })}
        evidence={[ineligible]}
        onEvidenceSelect={vi.fn()}
        selection={{ start: 8, end: 12 }}
      />,
    )

    await user.type(screen.getByLabelText('问题'), '有可靠证据吗？')
    await user.click(screen.getByRole('button', { name: '解释片段' }))

    expect(await screen.findByText(/没有通过门控的证据/)).toBeVisible()
    expect(screen.queryByRole('link', { name: /证据/ })).not.toBeInTheDocument()
    expect(screen.getByText(/结论保持 unknown/)).toBeVisible()
  })

  it('rejects generated text whose citation is not eligible evidence in the selected segment', async () => {
    const user = userEvent.setup()
    render(
      <QuestionPanel
        analysisId={analysisId}
        ask={vi.fn().mockResolvedValue({
          mode: 'llm',
          text: '这是一条没有当前证据支撑的音乐事实。',
          evidence_ids: ['00000000-0000-4000-8000-000000000099'],
        })}
        evidence={[evidence]}
        onEvidenceSelect={vi.fn()}
        selection={{ start: 8, end: 12 }}
      />,
    )

    await user.type(screen.getByLabelText('问题'), '这里是什么和弦？')
    await user.click(screen.getByRole('button', { name: '解释片段' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/未通过 Evidence 校验/)
    expect(screen.queryByText(/没有当前证据支撑的音乐事实/)).not.toBeInTheDocument()
  })
})
