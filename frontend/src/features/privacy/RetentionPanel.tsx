import { useEffect, useState } from 'react'
import { ApiError, deleteAnalysis } from '../../api/client'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'

export type DeleteTransport = (analysisId: string) => Promise<void>

export interface RetentionPanelProps {
  analysisId: string
  clock?: () => number
  expiresAt: string | null
  onDeleted: () => void
  remove?: DeleteTransport
}

export function RetentionPanel({
  analysisId,
  clock = Date.now,
  expiresAt,
  onDeleted,
  remove = deleteAnalysis,
}: RetentionPanelProps) {
  const [now, setNow] = useState(clock)
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const expiry = expiresAt === null ? Number.NaN : Date.parse(expiresAt)
  const expired = Number.isFinite(expiry) && expiry <= now

  useEffect(() => {
    const interval = window.setInterval(() => setNow(clock()), 1_000)
    return () => window.clearInterval(interval)
  }, [clock])

  const submitDeletion = async () => {
    if (!confirmed || pending || expired || !Number.isFinite(expiry)) return
    setPending(true)
    setError(null)
    try {
      await remove(analysisId)
      onDeleted()
    } catch (reason) {
      setError(deletionErrorMessage(reason))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="retention-panel" aria-labelledby="retention-title">
      <p className="eyebrow">加密保留与删除</p>
      <h2 id="retention-title">数据生命周期</h2>
      <p>{retentionText(expiry, now)}</p>
      <p>主动删除会先销毁数据密钥，再清除密文、分析结果、解释与访问权，操作不可恢复。</p>
      <label className="retention-panel__confirmation">
        <input
          checked={confirmed}
          disabled={expired || !Number.isFinite(expiry) || pending}
          onChange={(event) => setConfirmed(event.currentTarget.checked)}
          type="checkbox"
        />
        <span>我了解删除不可恢复</span>
      </label>
      {error ? (
        <ErrorNotice title="没有删除分析" action={error} />
      ) : null}
      <Button
        disabled={!confirmed || pending || expired || !Number.isFinite(expiry)}
        onClick={() => void submitDeletion()}
        variant="danger"
      >
        {pending ? '正在删除' : error ? '重新尝试删除' : '永久删除分析'}
      </Button>
    </section>
  )
}

function deletionErrorMessage(reason: unknown): string {
  if (!(reason instanceof ApiError)) {
    return '删除未完成，当前分析仍然保留；请检查连接后手动重试。'
  }
  const messages: Record<string, string> = {
    csrf_unavailable: '安全校验已失效，当前分析仍然保留；请刷新页面后重试。',
    network_error: '网络连接中断，当前分析仍然保留；系统不会自动重试。',
    not_found: '分析已删除、到期或访问凭证无效。',
  }
  return messages[reason.code] ?? '删除未完成，当前分析仍然保留；请手动重试。'
}

export function retentionText(expiry: number, now: number): string {
  if (!Number.isFinite(expiry)) return '服务端未提供合法的保留期限。'
  if (expiry <= now) return '保留期限已到，分析不再可访问。'
  const remaining = expiry - now
  if (remaining < 60_000) return '根据服务端期限，剩余不足 1 分钟。'
  const totalMinutes = Math.floor(remaining / 60_000)
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `根据服务端期限，剩余 ${hours} 小时 ${minutes} 分钟。`
}
