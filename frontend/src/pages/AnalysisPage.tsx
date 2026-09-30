import { useState } from 'react'
import { analysisIdPattern, getAnalysisStatus, type UploadTransport } from '../api/client'
import type { UploadAccepted } from '../api/types'
import { Button } from '../components/Button'
import { Panel } from '../components/Panel'
import { AnalysisProgress } from '../features/jobs/AnalysisProgress'
import type { StatusLoader } from '../features/jobs/useAnalysisStatus'
import type { DeleteTransport } from '../features/privacy/RetentionPanel'
import type { ResultLoader } from '../features/workspace/useAnalysisResult'
import { UploadForm } from '../features/upload/UploadForm'
import { Icon } from '../components/Icon'
import { AccountPanel } from '../features/account/AccountPanel'
import type { AccountUser, SavedDetail } from '../api/account'
import { AnalysisWorkspace } from '../features/workspace/AnalysisWorkspace'

export interface AnalysisPageProps {
  loadResult?: ResultLoader
  loadStatus?: StatusLoader
  removeAnalysis?: DeleteTransport
  upload?: UploadTransport
}

export function AnalysisPage({
  loadResult,
  loadStatus,
  removeAnalysis,
  upload,
}: AnalysisPageProps = {}) {
  const [analysisId, setAnalysisId] = useState(readAnalysisId)
  const [deleted, setDeleted] = useState(false)
  const [account, setAccount] = useState<AccountUser | null>(null)
  const [savedDetail, setSavedDetail] = useState<SavedDetail | null>(null)
  const [libraryVersion, setLibraryVersion] = useState(0)
  const [accountPanelOpen, setAccountPanelOpen] = useState(false)

  const acceptUpload = (accepted: UploadAccepted) => {
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.set('analysis', accepted.analysis_id)
    window.history.replaceState(null, '', nextUrl)
    setDeleted(false)
    setSavedDetail(null)
    setAnalysisId(accepted.analysis_id)
  }

  const startAnother = () => {
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.delete('analysis')
    window.history.replaceState(null, '', nextUrl)
    setDeleted(false)
    setSavedDetail(null)
    setAnalysisId(null)
  }

  const finishDeletion = () => {
    const nextUrl = new URL(window.location.href)
    nextUrl.searchParams.delete('analysis')
    window.history.replaceState(null, '', nextUrl)
    setAnalysisId(null)
    setDeleted(true)
  }

  const openSaved = async (detail: SavedDetail) => {
    // A saved snapshot never contains audio. Reuse the short-lived analysis only
    // when this browser still holds its separate playback capability.
    try {
      const status = await getAnalysisStatus(detail.original_analysis_id)
      if (status.stage === 'complete') {
        const nextUrl = new URL(window.location.href)
        nextUrl.searchParams.set('analysis', detail.original_analysis_id)
        window.history.replaceState(null, '', nextUrl)
        setDeleted(false)
        setSavedDetail(null)
        setAnalysisId(detail.original_analysis_id)
        return
      }
    } catch {
      // Expired analyses and other browsers can still view their private snapshot.
    }
    setSavedDetail(detail)
  }

  return (
    <div className={`app-shell${accountPanelOpen ? ' app-shell--account-open' : ''}`}>
      <header className="masthead">
        <p className="brand">
          <span className="brand-mark">
            <Icon name="music" />
          </span>
          MuseEcho<span className="brand-caption">听见 · 看见</span>
        </p>
        <p className="edition-mark">音乐解析工作室</p>
      </header>

      <main
        aria-label="MuseEcho 音乐解析工作区"
        className={`analysis-workspace${analysisId || savedDetail ? ' analysis-workspace--active' : ''}`}
      >
        <section
          aria-labelledby="workspace-title"
          className={`workspace-intro${analysisId ? ' workspace-intro--compact' : ''}`}
        >
          <div>
            <p className="eyebrow">聆听证据，而非猜测</p>
            <h1 className="display-title" id="workspace-title">
              看见音乐的<span className="title-accent">结构</span>
            </h1>
          </div>
          <p className="intro-copy">
            沿着时间线聆听节奏、动态强弱与局部和声，发现歌曲的变化。
          </p>
        </section>

        <AccountPanel
          onAccountChange={setAccount}
          onPanelOpenChange={setAccountPanelOpen}
          onOpenSaved={(detail) => { void openSaved(detail) }}
          refreshKey={libraryVersion}
        />

        <Panel
          className={`workflow-panel${analysisId ? ' workflow-panel--active' : ''}`}
          eyebrow={
            savedDetail ? '私人歌曲库 · 复看分析' : analysisId ? '聆听 · 定位 · 探索' : deleted ? '数据已清除' : '等待音频'
          }
          title={savedDetail ? savedDetail.title : analysisId ? '音乐工作台' : '分析流程'}
        >
          {savedDetail ? (
            <div className="active-analysis">
              <Button onClick={() => setSavedDetail(null)} variant="secondary">返回当前工作台</Button>
              <AnalysisWorkspace analysisId={savedDetail.analysis.analysis_id} snapshot={savedDetail.analysis} />
            </div>
          ) : analysisId ? (
            <div className="active-analysis">
              <AnalysisProgress
                analysisId={analysisId}
                loadResult={loadResult}
                loadStatus={loadStatus}
                onDeleted={finishDeletion}
                removeAnalysis={removeAnalysis}
                accountLoggedIn={account !== null}
                onSaved={() => setLibraryVersion((value) => value + 1)}
              />
              <Button onClick={startAnother} variant="secondary">
                分析其他音频
              </Button>
            </div>
          ) : deleted ? (
            <div className="deleted-analysis" role="status">
              <h2>分析已永久删除</h2>
              <p>
                本次临时分析、加密音频和访问权已从服务端清除，无法恢复。若曾保存到私人歌曲库，请在歌曲库管理保存副本。
              </p>
              <Button onClick={startAnother}>分析新的音频</Button>
            </div>
          ) : (
            <div className="empty-workflow">
              <div>
                <h2 className="empty-workflow__title">开始解析</h2>
                <p className="empty-workflow__copy">
                  带来一段音频，沿着节奏与和声，听见更多细节。
                </p>
                <UploadForm onAccepted={acceptUpload} onUpload={upload} />
              </div>
              <aside className="workflow-guide">
                <p className="eyebrow">一段音乐，逐层发现</p>
                <ol className="workflow-steps" aria-label="解析步骤">
                  <li>
                    <div>
                      <strong>选择与验证音频</strong>
                      <p>从你的本地音乐开始。</p>
                    </div>
                  </li>
                  <li>
                    <div>
                      <strong>提取可复核证据</strong>
                      <p>读懂节奏、调性与动态变化。</p>
                    </div>
                  </li>
                  <li>
                    <div>
                      <strong>沿时间轴呈现结果</strong>
                      <p>选择片段，回听并探索和弦。</p>
                    </div>
                  </li>
                </ol>
                <p className="workflow-guide__note">
                  你的音频加密保留，最长 24 小时。随时可以主动删除。
                </p>
              </aside>
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
