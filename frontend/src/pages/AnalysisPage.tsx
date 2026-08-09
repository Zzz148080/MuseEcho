import { useState } from 'react'
import { analysisIdPattern, type UploadTransport } from '../api/client'
import type { UploadAccepted } from '../api/types'
import { Button } from '../components/Button'
import { Panel } from '../components/Panel'
import { AnalysisProgress } from '../features/jobs/AnalysisProgress'
import type { StatusLoader } from '../features/jobs/useAnalysisStatus'
import { UploadForm } from '../features/upload/UploadForm'

export interface AnalysisPageProps {
  loadStatus?: StatusLoader
  upload?: UploadTransport
}

export function AnalysisPage({ loadStatus, upload }: AnalysisPageProps = {}) {
  const [analysisId, setAnalysisId] = useState(readAnalysisId)

  const acceptUpload = (accepted: UploadAccepted) => {
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.set('analysis', accepted.analysis_id)
    window.history.replaceState(null, '', nextUrl)
    setAnalysisId(accepted.analysis_id)
  }

  const startAnother = () => {
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.delete('analysis')
    window.history.replaceState(null, '', nextUrl)
    setAnalysisId(null)
  }

  return (
    <div className="app-shell">
      <header className="masthead">
        <p className="brand">MuseEcho</p>
        <p className="edition-mark">Evidence-led music analysis</p>
      </header>

      <main
        aria-label="MuseEcho 音乐解析工作区"
        className="analysis-workspace"
      >
        <section aria-labelledby="workspace-title" className="workspace-intro">
          <div>
            <p className="eyebrow">聆听证据，而非猜测</p>
            <h1 className="display-title" id="workspace-title">
              看见音乐的结构
            </h1>
          </div>
          <p className="intro-copy">
            MuseEcho 将可验证的音频证据整理到同一条时间线上。证据不足时，结果会明确标记为 unknown。
          </p>
        </section>

        <Panel
          className="workflow-panel"
          eyebrow={analysisId ? '实时状态' : '等待音频'}
          title="分析流程"
        >
          {analysisId ? (
            <div className="active-analysis">
              <AnalysisProgress analysisId={analysisId} loadStatus={loadStatus} />
              <Button onClick={startAnother} variant="secondary">
                分析其他音频
              </Button>
            </div>
          ) : (
            <div className="empty-workflow">
              <div>
                <h2 className="empty-workflow__title">开始解析</h2>
                <p className="empty-workflow__copy">
                  上传前请确认文件限制、合法使用与加密保留规则。分析事实只来自后端真实证据。
                </p>
                <UploadForm onAccepted={acceptUpload} onUpload={upload} />
              </div>
              <ol className="workflow-steps" aria-label="解析步骤">
                <li>选择与验证音频</li>
                <li>提取可复核证据</li>
                <li>沿时间轴呈现结果</li>
              </ol>
            </div>
          )}
        </Panel>
      </main>
    </div>
  )
}

function readAnalysisId(): string | null {
  const candidate = new URL(window.location.href).searchParams.get('analysis')
  return candidate && analysisIdPattern.test(candidate) ? candidate : null
}
