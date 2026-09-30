import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { ChordResult } from '../../api/types'
import type { AnalysisResult } from '../../api/types'
import { saveAnalysis } from '../../api/account'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import {
  FULLSCREEN_CHORD_DETAIL_QUERY,
  useMediaQuery,
} from '../../hooks/useMediaQuery'
import { ChordDetails } from '../chords/ChordDetails'
import { MusicDNA } from '../dna/MusicDNA'
import { AudioPlayer } from '../player/AudioPlayer'
import { RetentionPanel, type DeleteTransport } from '../privacy/RetentionPanel'
import { Timeline } from '../timeline/Timeline'
import { useTimeline } from '../timeline/useTimeline'
import { AnalysisFeatureHub } from './AnalysisFeatureHub'
import { useAnalysisResult, type ResultLoader } from './useAnalysisResult'
import { WorkspaceNavigation, type WorkspaceView } from './WorkspaceNavigation'
import { isUsableConfidence, isVisibleChordCandidate } from '../confidence'

export interface AnalysisWorkspaceProps {
  analysisId: string
  expiresAt?: string | null
  loadResult?: ResultLoader
  onDeleted?: () => void
  removeAnalysis?: DeleteTransport
  accountLoggedIn?: boolean
  onSaved?: () => void
  snapshot?: AnalysisResult
}

export function AnalysisWorkspace({
  analysisId,
  expiresAt = null,
  loadResult,
  onDeleted = () => undefined,
  removeAnalysis,
  accountLoggedIn = false,
  onSaved,
  snapshot,
}: AnalysisWorkspaceProps) {
  const query = useAnalysisResult(
    analysisId,
    snapshot ? async () => snapshot : loadResult,
    snapshot ? 'saved' : 'live',
  )
  if (query.isPending) {
    return (
      <div className="workspace-loading" role="status">
        <p>正在读取已持久化的分析结果…</p>
        <div className="workspace-skeleton" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
    )
  }
  if (query.error || !query.data) {
    return (
      <div className="workspace-error">
        <ErrorNotice
          title="无法读取分析结果"
          action="请检查连接后手动重试；页面不会用演示数据替代。"
        />
        <Button onClick={() => void query.refetch()} variant="secondary">
          重试读取结果
        </Button>
      </div>
    )
  }
  return (
    <LoadedWorkspace
      expiresAt={expiresAt}
      key={query.data.analysis_id}
      onDeleted={onDeleted}
      removeAnalysis={removeAnalysis}
      result={query.data}
      accountLoggedIn={accountLoggedIn}
      onSaved={onSaved}
      snapshotMode={Boolean(snapshot)}
    />
  )
}

interface LoadedWorkspaceProps {
  expiresAt: string | null
  onDeleted: () => void
  removeAnalysis?: DeleteTransport
  result: NonNullable<ReturnType<typeof useAnalysisResult>['data']>
  accountLoggedIn: boolean
  onSaved?: () => void
  snapshotMode: boolean
}

function LoadedWorkspace({
  expiresAt,
  onDeleted,
  removeAnalysis,
  result,
  accountLoggedIn,
  onSaved,
  snapshotMode,
}: LoadedWorkspaceProps) {
  const queryClient = useQueryClient()
  const timeline = useTimeline(result.track.duration_seconds)
  const currentSection = result.sections.find(
    (section) =>
      timeline.currentTime >= section.start_seconds &&
      timeline.currentTime < section.end_seconds &&
      isUsableConfidence(section.confidence),
  )
  const currentChord = result.chords.find(
    (chord) =>
      timeline.currentTime >= chord.start_seconds &&
      timeline.currentTime < chord.end_seconds &&
      isVisibleChordCandidate(chord),
  )
  const [currentView, setCurrentView] = useState<WorkspaceView>('overview')
  const [selectedChord, setSelectedChord] = useState<ChordResult | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailSession, setDetailSession] = useState(0)
  const [saveTitle, setSaveTitle] = useState('我的歌曲分析')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle')
  const [saveError, setSaveError] = useState('')
  const isFullscreenDetail = useMediaQuery(FULLSCREEN_CHORD_DETAIL_QUERY)
  const workspaceRoot = useRef<HTMLDivElement | null>(null)
  const lastChordTrigger = useRef<HTMLButtonElement | null>(null)
  const detailPanel = useRef<HTMLElement | null>(null)
  const restoreFocusAfterClose = useRef(false)

  const fullscreenDetailOpen =
    isFullscreenDetail && detailOpen && selectedChord !== null

  useEffect(() => {
    if (!detailOpen || !selectedChord) return
    detailPanel.current
      ?.querySelector<HTMLButtonElement>('[data-detail-return]')
      ?.focus()
  }, [detailOpen, isFullscreenDetail, selectedChord])

  useEffect(() => {
    if (detailOpen || !restoreFocusAfterClose.current) return
    restoreFocusAfterClose.current = false
    const trigger = lastChordTrigger.current
    if (trigger?.isConnected) trigger.focus()
  }, [detailOpen])

  useEffect(() => {
    if (!fullscreenDetailOpen) return
    const backgroundRoot =
      workspaceRoot.current?.closest<HTMLElement>('.app-shell') ??
      workspaceRoot.current
    if (!backgroundRoot) return

    backgroundRoot.setAttribute('inert', '')
    backgroundRoot.setAttribute('aria-hidden', 'true')
    document.body.classList.add('workspace-mobile-detail-open')
    return () => {
      backgroundRoot.removeAttribute('inert')
      backgroundRoot.removeAttribute('aria-hidden')
      document.body.classList.remove('workspace-mobile-detail-open')
    }
  }, [fullscreenDetailOpen])

  const openChord = (chord: ChordResult, trigger: HTMLButtonElement) => {
    lastChordTrigger.current = trigger
    restoreFocusAfterClose.current = false
    setSelectedChord(chord)
    setDetailSession((session) => session + 1)
    setDetailOpen(true)
  }

  const closeChord = () => {
    restoreFocusAfterClose.current = true
    setDetailOpen(false)
  }

  const clearChord = () => {
    restoreFocusAfterClose.current = false
    lastChordTrigger.current = null
    setDetailOpen(false)
    setSelectedChord(null)
  }

  const changeView = (next: WorkspaceView) => {
    restoreFocusAfterClose.current = false
    setDetailOpen(false)
    setCurrentView(next)
  }

  const handleFullscreenDetailKeyDown = (
    event: ReactKeyboardEvent<HTMLElement>,
  ) => {
    if (!isFullscreenDetail) return
    if (event.key === 'Escape') {
      event.preventDefault()
      closeChord()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = detailPanel.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )
    if (!focusable?.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const leavingDialog = event.shiftKey
      ? document.activeElement === first
      : document.activeElement === last
    if (!leavingDialog) return
    event.preventDefault()
    ;(event.shiftKey ? last : first).focus()
  }

  const finishDeletion = () => {
    void queryClient.cancelQueries({
      queryKey: ['analysis-status', result.analysis_id],
    })
    void queryClient.cancelQueries({
      queryKey: ['analysis-result', result.analysis_id],
    })
    queryClient.removeQueries({
      queryKey: ['analysis-status', result.analysis_id],
    })
    queryClient.removeQueries({
      queryKey: ['analysis-result', result.analysis_id],
    })
    onDeleted()
  }

  const saveCurrent = async () => {
    if (saveState !== 'idle') return
    setSaveError('')
    setSaveState('saving')
    try {
      await saveAnalysis(result.analysis_id, saveTitle)
      setSaveState('saved')
      onSaved?.()
    } catch {
      setSaveError('保存未完成。请确认仍在 24 小时保留期内、歌曲库未满，然后重试。')
      setSaveState('idle')
    }
  }

  const chordDetail =
    detailOpen && selectedChord ? (
      <aside
        aria-label={isFullscreenDetail ? undefined : '当前和弦详情'}
        aria-labelledby={isFullscreenDetail ? 'chord-details-title' : undefined}
        aria-modal={isFullscreenDetail ? true : undefined}
        className="workspace-detail"
        onKeyDown={handleFullscreenDetailKeyDown}
        ref={detailPanel}
        role={isFullscreenDetail ? 'dialog' : undefined}
      >
        <Button data-detail-return onClick={closeChord} variant="secondary">
          返回结构地图
        </Button>
        <ChordDetails
          chord={selectedChord}
          key={`${selectedChord.id}-${detailSession}`}
        />
      </aside>
    ) : null

  return (
    <>
      <div
        className="music-workspace"
        data-detail-open={detailOpen}
        ref={workspaceRoot}
      >
        {result.source_kind !== 'real' && (
          <p className="source-kind">
            {result.source_kind === 'synthetic_test'
              ? '合成测试数据'
              : '演示数据'}{' '}
            · 仅用于展示与验证
          </p>
        )}
        {snapshotMode ? <p className="saved-snapshot-note" role="status">正在复看私人歌曲库中的结构化分析。原音频按最长 24 小时规则清理，此处不提供播放；时间轴仍可用于定位和探索和弦。</p> : null}
        <WorkspaceNavigation current={currentView} onChange={changeView} />
        <div className="music-workspace__stage">
          {!snapshotMode && <AudioPlayer
            analysisId={result.analysis_id}
            timeline={timeline}
            currentSection={currentSection}
            currentChord={currentChord}
            onLocateSection={() => {
              changeView('map')
              if (currentSection) timeline.seek(currentSection.start_seconds)
            }}
            onExploreChord={(trigger) => {
              setCurrentView('map')
              if (currentChord) openChord(currentChord, trigger)
            }}
          />}
          {currentView === 'overview' ? (
            <section
              aria-label="歌曲概览"
              className="workspace-view workspace-view--overview"
            >
              <MusicDNA result={result} onOpenMap={() => changeView('map')} />
            </section>
          ) : null}

          {currentView === 'map' ? (
            <section
              aria-label="结构地图工作区"
              className="workspace-view workspace-view--map"
            >
              <div className="workspace-map-layout">
                <Timeline
                  offline={snapshotMode}
                  onChordDeselect={clearChord}
                  onChordSelect={openChord}
                  result={result}
                  selectedChord={selectedChord}
                  timeline={timeline}
                />
                {!isFullscreenDetail ? chordDetail : null}
              </div>
            </section>
          ) : null}

          {currentView === 'deep' ? (
            <div className="workspace-view workspace-view--deep">
              <AnalysisFeatureHub
                onOpenMap={() => changeView('map')}
                result={result}
              />
            </div>
          ) : null}

          <div className="analysis-support">
            {!snapshotMode && accountLoggedIn && result.source_kind === 'real' && <div className="save-analysis">
              <div><strong>保存到我的歌曲库</strong><p>仅保存分析数据；原音频仍会按期限删除。最多 100 首。</p></div>
              <label>歌曲标题<input maxLength={120} value={saveTitle} onChange={(event) => setSaveTitle(event.target.value)} disabled={saveState !== 'idle'} /></label>
              <Button onClick={() => void saveCurrent()} disabled={saveState !== 'idle' || !saveTitle.trim()}>{saveState === 'saving' ? '保存中' : saveState === 'saved' ? '已保存' : '保存这首分析'}</Button>
              {saveError && <p role="alert">{saveError}</p>}
            </div>}
            {!snapshotMode && <RetentionPanel
              analysisId={result.analysis_id}
              accountLoggedIn={accountLoggedIn}
              expiresAt={expiresAt}
              onDeleted={finishDeletion}
              remove={removeAnalysis}
            />}
          </div>
        </div>
      </div>
      {fullscreenDetailOpen ? createPortal(chordDetail, document.body) : null}
    </>
  )
}
