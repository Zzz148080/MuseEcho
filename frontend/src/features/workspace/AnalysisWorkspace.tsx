import {
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useRef,
  useState,
} from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { ChordResult } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import {
  FULLSCREEN_CHORD_DETAIL_QUERY,
  useMediaQuery,
} from '../../hooks/useMediaQuery'
import { ChordDetails } from '../chords/ChordDetails'
import { MusicDNA } from '../dna/MusicDNA'
import { AudioPlayer } from '../player/AudioPlayer'
import {
  RetentionPanel,
  type DeleteTransport,
} from '../privacy/RetentionPanel'
import { Timeline } from '../timeline/Timeline'
import { useTimeline } from '../timeline/useTimeline'
import { AnalysisFeatureHub } from './AnalysisFeatureHub'
import {
  useAnalysisResult,
  type ResultLoader,
} from './useAnalysisResult'
import {
  WorkspaceNavigation,
  type WorkspaceView,
} from './WorkspaceNavigation'

export interface AnalysisWorkspaceProps {
  analysisId: string
  expiresAt?: string | null
  loadResult?: ResultLoader
  onDeleted?: () => void
  removeAnalysis?: DeleteTransport
}

export function AnalysisWorkspace({
  analysisId,
  expiresAt = null,
  loadResult,
  onDeleted = () => undefined,
  removeAnalysis,
}: AnalysisWorkspaceProps) {
  const query = useAnalysisResult(analysisId, loadResult)
  if (query.isPending) {
    return <p className="workspace-loading" role="status">正在读取已持久化的分析结果…</p>
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
    />
  )
}

interface LoadedWorkspaceProps {
  expiresAt: string | null
  onDeleted: () => void
  removeAnalysis?: DeleteTransport
  result: NonNullable<ReturnType<typeof useAnalysisResult>['data']>
}

function LoadedWorkspace({
  expiresAt,
  onDeleted,
  removeAnalysis,
  result,
}: LoadedWorkspaceProps) {
  const queryClient = useQueryClient()
  const timeline = useTimeline(result.track.duration_seconds)
  const [currentView, setCurrentView] = useState<WorkspaceView>('overview')
  const [selectedChord, setSelectedChord] = useState<ChordResult | null>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailSession, setDetailSession] = useState(0)
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

  const keepFocusInMobileDetail = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (!isFullscreenDetail || event.key !== 'Tab') return
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
    void queryClient.cancelQueries({ queryKey: ['analysis-status', result.analysis_id] })
    void queryClient.cancelQueries({ queryKey: ['analysis-result', result.analysis_id] })
    queryClient.removeQueries({ queryKey: ['analysis-status', result.analysis_id] })
    queryClient.removeQueries({ queryKey: ['analysis-result', result.analysis_id] })
    onDeleted()
  }

  const chordDetail = detailOpen && selectedChord ? (
    <aside
      aria-label={isFullscreenDetail ? undefined : '当前和弦详情'}
      aria-labelledby={
        isFullscreenDetail ? 'chord-details-title' : undefined
      }
      aria-modal={isFullscreenDetail ? true : undefined}
      className="workspace-detail"
      onKeyDown={keepFocusInMobileDetail}
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
      <div className="music-workspace" ref={workspaceRoot}>
        <WorkspaceNavigation current={currentView} onChange={changeView} />
        <div className="music-workspace__stage">
          <AudioPlayer analysisId={result.analysis_id} timeline={timeline} />
          {currentView === 'overview' ? (
            <section
              aria-label="歌曲概览"
              className="workspace-view workspace-view--overview"
            >
              <MusicDNA result={result} />
            </section>
          ) : null}

          {currentView === 'map' ? (
            <section
              aria-label="结构地图工作区"
              className="workspace-view workspace-view--map"
            >
              <div className="workspace-map-layout">
                <Timeline
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
            <RetentionPanel
              analysisId={result.analysis_id}
              expiresAt={expiresAt}
              onDeleted={finishDeletion}
              remove={removeAnalysis}
            />
          </div>
        </div>
      </div>
      {fullscreenDetailOpen ? createPortal(chordDetail, document.body) : null}
    </>
  )
}
