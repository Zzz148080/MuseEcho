import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { ChordResult } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
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
  const lastChordTrigger = useRef<HTMLButtonElement | null>(null)

  const openChord = (chord: ChordResult, trigger: HTMLButtonElement) => {
    lastChordTrigger.current = trigger
    setSelectedChord(chord)
  }

  const closeChord = () => {
    setSelectedChord(null)
    lastChordTrigger.current?.focus()
  }

  const finishDeletion = () => {
    void queryClient.cancelQueries({ queryKey: ['analysis-status', result.analysis_id] })
    void queryClient.cancelQueries({ queryKey: ['analysis-result', result.analysis_id] })
    queryClient.removeQueries({ queryKey: ['analysis-status', result.analysis_id] })
    queryClient.removeQueries({ queryKey: ['analysis-result', result.analysis_id] })
    onDeleted()
  }

  return (
    <div className="music-workspace">
      <WorkspaceNavigation current={currentView} onChange={setCurrentView} />
      <div className="music-workspace__stage">
        <AudioPlayer analysisId={result.analysis_id} timeline={timeline} />
        {currentView === 'overview' ? (
          <section aria-label="歌曲概览" className="workspace-view workspace-view--overview">
            <MusicDNA result={result} />
          </section>
        ) : null}

        {currentView === 'map' ? (
          <section aria-label="结构地图工作区" className="workspace-view workspace-view--map">
            <div className={`workspace-map-layout${selectedChord ? ' workspace-map-layout--detail' : ''}`}>
              <Timeline
                onChordSelect={openChord}
                result={result}
                selectedChord={selectedChord}
                timeline={timeline}
              />
              {selectedChord ? (
                <aside aria-label="当前和弦详情" className="workspace-detail">
                  <Button onClick={closeChord} variant="secondary">
                    返回结构地图
                  </Button>
                  <ChordDetails chord={selectedChord} />
                </aside>
              ) : null}
            </div>
          </section>
        ) : null}

        {currentView === 'deep' ? (
          <div className="workspace-view workspace-view--deep">
            <AnalysisFeatureHub onOpenMap={() => setCurrentView('map')} result={result} />
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
  )
}
