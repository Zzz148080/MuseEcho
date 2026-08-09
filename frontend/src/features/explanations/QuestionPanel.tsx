import { useState, type FormEvent } from 'react'
import { ApiError, createExplanation } from '../../api/client'
import type {
  EvidenceResult,
  ExplanationRequest,
  ExplanationResponse,
} from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import { formatTime } from '../timeline/Timeline'
import type { TimeSelection } from '../timeline/useTimeline'
import { EvidenceList } from './EvidenceList'

export type ExplanationTransport = (
  analysisId: string,
  request: ExplanationRequest,
) => Promise<ExplanationResponse>

export interface QuestionPanelProps {
  analysisId: string
  ask?: ExplanationTransport
  evidence: EvidenceResult[]
  onEvidenceSelect: (evidence: EvidenceResult) => void
  selection: TimeSelection | null
}

export function QuestionPanel({
  analysisId,
  ask = createExplanation,
  evidence,
  onEvidenceSelect,
  selection,
}: QuestionPanelProps) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<ExplanationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const selectionIsValid = validSelection(selection)

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (!selection || !selectionIsValid || !trimmed || trimmed.length > 500) return
    setPending(true)
    setAnswer(null)
    setError(null)
    try {
      const response = await ask(analysisId, {
        question: trimmed,
        start_seconds: selection.start,
        end_seconds: selection.end,
      })
      if (!generatedCitationsAreValid(response, evidence, selection)) {
        throw new ApiError(0, 'invalid_server_response')
      }
      setAnswer(response)
    } catch (reason) {
      setError(explanationErrorMessage(reason))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="question-panel" aria-labelledby="question-title">
      <p className="eyebrow">Evidence-grounded explanation</p>
      <h2 id="question-title">片段问答</h2>
      <p className="question-panel__selection">
        {selection === null
          ? '请先在结构地图选择片段，再提出问题。'
          : selectionIsValid
            ? `当前片段 ${formatTime(selection.start)}–${formatTime(selection.end)}`
            : '片段长度不能超过 2 分钟，请缩短选区。'}
      </p>
      <form onSubmit={(event) => void submit(event)}>
        <label>
          <span>问题</span>
          <textarea
            maxLength={500}
            onChange={(event) => setQuestion(event.currentTarget.value)}
            value={question}
          />
        </label>
        <Button
          disabled={!selectionIsValid || !question.trim() || pending}
          type="submit"
        >
          {pending ? '正在解释' : error ? '重新解释片段' : '解释片段'}
        </Button>
      </form>
      {error ? (
        <ErrorNotice title="无法解释这个片段" action={error} />
      ) : null}
      {answer ? (
        <div className="question-answer" role="status">
          <p className="answer-mode">{answer.mode === 'llm' ? 'LLM 解释' : '确定性回退'}</p>
          <p>{answer.text}</p>
          <EvidenceList
            evidence={evidence}
            evidenceIds={answer.evidence_ids}
            onSelect={onEvidenceSelect}
          />
        </div>
      ) : null}
    </section>
  )
}

function validSelection(selection: TimeSelection | null): boolean {
  if (!selection) return false
  const duration = selection.end - selection.start
  return (
    Number.isFinite(selection.start) &&
    Number.isFinite(selection.end) &&
    selection.start >= 0 &&
    duration > 0 &&
    duration <= 120
  )
}

function explanationErrorMessage(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return '无法读取解释结果，请检查连接后手动重试。'
  }
  const messages: Record<string, string> = {
    csrf_unavailable: '安全校验已失效，请刷新页面；若仍失败，请重新上传音频。',
    explanation_rate_limited: '请求过于频繁，请约一分钟后手动重试。',
    invalid_explanation_request: '问题或片段不合法，请选择不超过 2 分钟的片段。',
    invalid_server_response: '服务端解释未通过 Evidence 校验，未显示任何生成式音乐事实；请稍后手动重试。',
    network_error: '网络连接中断；系统不会自动重复问题，请手动重试。',
    not_found: '分析已到期、删除或访问凭证无效，无法继续解释。',
    result_not_ready: '分析结果尚未准备完成，请稍后手动重试。',
  }
  return messages[reason.code] ?? '无法读取解释结果，请检查连接后手动重试。'
}

function generatedCitationsAreValid(
  response: ExplanationResponse,
  evidence: EvidenceResult[],
  selection: TimeSelection,
): boolean {
  if (response.mode !== 'llm') return true
  const eligibleIds = new Set(
    evidence
      .filter(
        (item) =>
          item.eligible_for_llm &&
          item.end_seconds > selection.start &&
          item.start_seconds < selection.end,
      )
      .map((item) => item.id),
  )
  return (
    response.evidence_ids.length > 0 &&
    response.evidence_ids.every((id) => eligibleIds.has(id))
  )
}
