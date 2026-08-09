import { useState } from 'react'
import type { ChordResult } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'
import { ChordDetails } from '../chords/ChordDetails'
import { MusicDNA } from '../dna/MusicDNA'
import { AudioPlayer } from '../player/AudioPlayer'
import { Timeline } from '../timeline/Timeline'
import { useTimeline } from '../timeline/useTimeline'
import {
  useAnalysisResult,
  type ResultLoader,
} from './useAnalysisResult'

export interface AnalysisWorkspaceProps {
  analysisId: string
  loadResult?: ResultLoader
}

export function AnalysisWorkspace({
  analysisId,
  loadResult,
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
  return <LoadedWorkspace result={query.data} />
}

function LoadedWorkspace({ result }: { result: NonNullable<ReturnType<typeof useAnalysisResult>['data']> }) {
  const timeline = useTimeline(result.track.duration_seconds)
  const [selectedChord, setSelectedChord] = useState<ChordResult | null>(null)

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
    </div>
  )
}
