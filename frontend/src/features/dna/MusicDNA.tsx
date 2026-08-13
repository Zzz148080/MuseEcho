import type { AnalysisResult } from '../../api/types'
import {
  ConfidenceBadge,
  type ConfidenceLevel,
} from '../../components/ConfidenceBadge'
import { confidenceLevel } from '../confidence'
import { formatTime } from '../timeline/Timeline'

export interface MusicDNAProps {
  result: AnalysisResult
}

export function MusicDNA({ result }: MusicDNAProps) {
  const { track } = result
  const bpmLevel = confidenceLevel(track.bpm_confidence)
  const keyLevel = confidenceLevel(track.key_confidence)
  const energy = result.time_series.find((item) => item.kind === 'energy')
  const energyMean = energy?.points.length
    ? energy.points.reduce((total, point) => total + point, 0) / energy.points.length
    : null

  return (
    <section className="music-dna" aria-labelledby="music-dna-title">
      <div className="music-dna__heading">
        <div>
          <p className="eyebrow">当前分析事实</p>
          <h2 id="music-dna-title">Music DNA</h2>
        </div>
      </div>

      <dl className="dna-facts">
        <Fact label="时长" value={formatTime(track.duration_seconds)} />
        <Fact
          confidence={bpmLevel}
          label="速度"
          value={bpmLevel === 'unknown' || track.bpm === null ? null : `${Math.round(track.bpm)} BPM`}
        />
        <Fact
          confidence={keyLevel}
          label="调性"
          value={
            keyLevel === 'unknown' || !track.key_tonic || !track.mode
              ? null
              : `${track.key_tonic} ${track.mode === 'major' ? '大调' : '小调'}`
          }
        />
        <Fact
          label="可靠拍点"
          value={
            bpmLevel !== 'unknown' && track.summary?.beat_positions_seconds.length
              ? `${track.summary.beat_positions_seconds.length} 个`
              : null
          }
        />
        <Fact
          label="平均能量"
          value={energyMean === null ? null : `${Math.round(energyMean * 100)}%`}
        />
      </dl>
    </section>
  )
}

interface FactProps {
  confidence?: ConfidenceLevel
  label: string
  value: string | null
}

function Fact({ confidence, label, value }: FactProps) {
  return (
    <div className="dna-fact">
      <dt>{label}</dt>
      <dd>
        <span>{value ?? '暂未判定'}</span>
        {confidence && confidence !== 'unknown' ? <ConfidenceBadge level={confidence} /> : null}
      </dd>
    </div>
  )
}
