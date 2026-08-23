import type { AnalysisResult } from '../../api/types'
import { Button } from '../../components/Button'
import { confidenceLevel } from '../confidence'

export interface AnalysisFeatureHubProps {
  onOpenMap: () => void
  result: AnalysisResult
}

export function AnalysisFeatureHub({ onOpenMap, result }: AnalysisFeatureHubProps) {
  const { track } = result
  const bpm =
    confidenceLevel(track.bpm_confidence) === 'unknown' || track.bpm === null
      ? '暂未判定'
      : `${Math.round(track.bpm)} BPM`
  const tonality =
    confidenceLevel(track.key_confidence) === 'unknown' ||
    !track.key_tonic ||
    !track.mode
      ? '暂未判定'
      : `${track.key_tonic} ${track.mode === 'major' ? '大调' : '小调'}`
  const chordCount = result.chords.filter((chord) => chord.symbol !== 'unknown').length
  const energyPoints =
    result.time_series.find((series) => series.kind === 'energy')?.points.length ?? 0

  return (
    <section aria-labelledby="feature-hub-title" className="feature-hub">
      <header className="feature-hub__header">
        <p className="eyebrow">按需展开真实证据</p>
        <h2 id="feature-hub-title">深入分析</h2>
      </header>
      <div className="feature-hub__grid">
        <FeatureFact label="节奏" value={bpm} />
        <FeatureFact label="调性" value={tonality} />
        <FeatureFact label="和弦线索" value={`${chordCount} 个可见候选`} />
        <FeatureFact label="动态强弱" value={`${energyPoints} 个采样点`} />
      </div>
      <Button onClick={onOpenMap} variant="secondary">
        在结构地图中查看
      </Button>
    </section>
  )
}

function FeatureFact({ label, value }: { label: string; value: string }) {
  return (
    <article className="feature-fact">
      <h3>{label}</h3>
      <p>{value}</p>
    </article>
  )
}
