import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { ChordResult, EvidenceResult } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import { ChordDetails } from '../chords/ChordDetails'
import { MusicDNA } from '../dna/MusicDNA'
import {
  QuestionPanel,
  type ExplanationTransport,
} from '../explanations/QuestionPanel'
import { AudioPlayer } from '../player/AudioPlayer'
import {
  RetentionPanel,
  type DeleteTransport,
} from '../privacy/RetentionPanel'
import { Timeline } from '../timeline/Timeline'
import { useTimeline } from '../timeline/useTimeline'
import {
  useAnalysisResult,
  type ResultLoader,
} from './useAnalysisResult'

export interface AnalysisWorkspaceProps {
  analysisId: string
  ask?: ExplanationTransport
  expiresAt?: string | null
  loadResult?: ResultLoader
  onDeleted?: () => void
  removeAnalysis?: DeleteTransport
}

export function AnalysisWorkspace({
  analysisId,
  ask,
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
      ask={ask}
      expiresAt={expiresAt}
      onDeleted={onDeleted}
      removeAnalysis={removeAnalysis}
      result={query.data}
    />
  )
}

interface LoadedWorkspaceProps {
  ask?: ExplanationTransport
  expiresAt: string | null
  onDeleted: () => void
  removeAnalysis?: DeleteTransport
  result: NonNullable<ReturnType<typeof useAnalysisResult>['data']>
}

function LoadedWorkspace({
  ask,
  expiresAt,
  onDeleted,
  removeAnalysis,
  result,
}: LoadedWorkspaceProps) {
  const queryClient = useQueryClient()
  const timeline = useTimeline(result.track.duration_seconds)
  const [selectedChord, setSelectedChord] = useState<ChordResult | null>(null)

  const selectEvidence = (evidence: EvidenceResult) => {
    timeline.seek(evidence.start_seconds)
    timeline.select(evidence.start_seconds, evidence.end_seconds)
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
      <div className="music-workspace__overview">
        <AudioPlayer analysisId={result.analysis_id} timeline={timeline} />
        <MusicDNA result={result} />
      </div>
      <Timeline
        onChordSelect={setSelectedChord}
        result={result}
        timeline={timeline}
      />
      <ChordDetails chord={selectedChord} />
      <div className="analysis-support">
        <QuestionPanel
          analysisId={result.analysis_id}
          ask={ask}
          evidence={result.evidence}
          onEvidenceSelect={selectEvidence}
          selection={timeline.selection}
        />
        <RetentionPanel
          analysisId={result.analysis_id}
          expiresAt={expiresAt}
          onDeleted={finishDeletion}
          remove={removeAnalysis}
        />
      </div>
    </div>
  )
}
