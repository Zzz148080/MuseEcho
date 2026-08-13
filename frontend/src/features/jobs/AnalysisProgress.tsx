import { ApiError } from '../../api/client'
import type { AnalysisStage, AnalysisStatus } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import { AnalysisWorkspace } from '../workspace/AnalysisWorkspace'
import type { ResultLoader } from '../workspace/useAnalysisResult'
import type { DeleteTransport } from '../privacy/RetentionPanel'
import {
  statusPollInterval,
  useAnalysisStatus,
  type StatusLoader,
} from './useAnalysisStatus'

const stageLabels: Record<AnalysisStage, string> = {
  queued: '等待分析',
  validating: '验证音频',
  decoding: '解码音频',
  rhythm: '分析节奏与能量',
  tonality: '分析调性',
  structure: '分析段落结构',
  chords: '分析和弦',
  evidence: '整理证据',
  complete: '分析完成',
  failed: '分析未完成',
  deleted: '分析已删除',
  expired: '分析已到期',
}

export interface AnalysisProgressProps {
  analysisId: string
  loadResult?: ResultLoader
  loadStatus?: StatusLoader
  onDeleted?: () => void
  removeAnalysis?: DeleteTransport
}

export function AnalysisProgress({
  analysisId,
  loadResult,
  loadStatus,
  onDeleted,
  removeAnalysis,
}: AnalysisProgressProps) {
  const query = useAnalysisStatus(analysisId, loadStatus)

  if (query.isPending) {
    return <p className="status-loading" role="status">正在读取真实分析状态…</p>
  }
  if (query.error || !query.data) {
    return (
      <div className="status-error">
        <ErrorNotice
          title="无法读取分析状态"
          action={statusErrorAction(query.error)}
        />
        <Button onClick={() => void query.refetch()} variant="secondary">
          重试
        </Button>
      </div>
    )
  }

  const status = query.data
  const percentage = Math.round(status.progress * 100)
  return (
    <div
      className={`analysis-progress${status.stage === 'complete' ? ' analysis-progress--complete' : ''}`}
    >
      <div className="analysis-progress__heading" aria-live="polite">
        <div>
          <p className="eyebrow">分析进度</p>
          <h2>{stageLabels[status.stage]}</h2>
        </div>
        <span className="edition-mark">{percentage}%</span>
      </div>

      <progress aria-label="分析进度" max={100} value={percentage} />
      <p
        className="stage-description"
        role={status.stage === 'failed' ? 'alert' : undefined}
      >
        {stageDescription(status)}
      </p>

      <dl className="status-metadata">
        <div>
          <dt>保留期限</dt>
          <dd>{formatExpiry(status.expires_at)}</dd>
        </div>
      </dl>
      {status.stage === 'complete' ? (
        <AnalysisWorkspace
          analysisId={analysisId}
          expiresAt={status.expires_at}
          loadResult={loadResult}
          onDeleted={onDeleted}
          removeAnalysis={removeAnalysis}
        />
      ) : null}
    </div>
  )
}

function stageDescription(status: AnalysisStatus): string {
  if (status.stage === 'queued') return '任务正在单工作队列中等待，不会用本地计时器伪造进度。'
  if (status.stage === 'complete') return '可验证分析已经持久化，可以继续查看结果。'
  if (status.stage === 'failed') {
    const code = status.error_code ?? 'analysis_failed'
    return `${analysisFailureMessage(code)}（稳定错误码：${code}）。`
  }
  if (status.stage === 'expired') return '加密音频与访问能力已按保留规则到期。'
  if (status.stage === 'deleted') return '这项分析已被主动删除。'
  return '当前百分比与阶段均来自 MuseEcho 后端检查点。'
}

function analysisFailureMessage(code: string): string {
  const messages: Record<string, string> = {
    analysis_input_unavailable: '加密音频输入不可用，请重新上传',
    analysis_workspace_unavailable: '安全分析工作区暂时不可用，请稍后重试',
    audio_decode_failed: '音频解码未完成，请检查文件后重新上传',
    invalid_audio: '音频内容无法验证，请重新选择文件',
    analysis_failed: '分析未完成，请重新上传或稍后重试',
  }
  return messages[code] ?? '分析未完成，请重新上传或稍后重试'
}

function statusErrorAction(reason: unknown): string {
  if (reason instanceof ApiError && reason.code === 'not_found') {
    return '访问凭证无效、已到期，或分析不存在。请返回并重新上传。'
  }
  return '请检查连接后重试；页面不会猜测任务进度。'
}

function formatExpiry(value: string | null): string {
  if (!value) return '服务端尚未提供'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '服务端时间无效'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(parsed)
}

export { statusPollInterval }
