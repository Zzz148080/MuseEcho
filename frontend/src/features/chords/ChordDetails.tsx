import type { ChordResult } from '../../api/types'
import { ConfidenceBadge } from '../../components/ConfidenceBadge'
import { confidenceLevel, isUsableConfidence } from '../confidence'
import { formatTime } from '../timeline/Timeline'

const functionLabels: Record<string, string> = {
  dominant: '属功能',
  'dominant-substitute': '属功能替代',
  predominant: '下属准备功能',
  tonic: '主功能',
  'tonic-prolongation': '主功能延展',
  'tonic-substitute': '主功能替代',
}

export interface ChordDetailsProps {
  chord: ChordResult | null
}

export function ChordDetails({ chord }: ChordDetailsProps) {
  if (!chord) {
    return (
      <section className="chord-details" aria-labelledby="chord-details-title">
        <h2 id="chord-details-title">和弦详情</h2>
        <p>点击时间轴中的和弦事件查看已持久化的确定性乐理。</p>
      </section>
    )
  }
  const theory =
    chord.symbol === 'unknown' || !isUsableConfidence(chord.confidence)
      ? null
      : chord.theory
  if (!theory) {
    return (
      <section className="chord-details" aria-labelledby="chord-details-title">
        <p className="eyebrow">
          {formatTime(chord.start_seconds)}–{formatTime(chord.end_seconds)}
        </p>
        <h2 id="chord-details-title">和弦详情</h2>
        <p className="unknown-copy">证据不足，前端不补全未持久化的乐理事实。</p>
      </section>
    )
  }

  return (
    <section className="chord-details" aria-labelledby="chord-details-title">
      <div className="chord-details__heading">
        <div>
          <p className="eyebrow">
            {formatTime(chord.start_seconds)}–{formatTime(chord.end_seconds)}
          </p>
          <h2 id="chord-details-title">{chord.symbol} 和弦</h2>
        </div>
        <ConfidenceBadge level={confidenceLevel(chord.confidence)} />
      </div>
      <dl className="theory-facts">
        <TheoryFact label="组成音" value={theory.pitch_classes.join(' · ')} />
        <TheoryFact label="音程" value={theory.intervals.join(' · ')} />
        <TheoryFact
          label="性质"
          value={
            theory.quality === 'major'
              ? '大三和弦'
              : theory.quality === 'minor'
                ? '小三和弦'
                : '不确定'
          }
        />
        <TheoryFact label="调内级数" value={theory.roman_numeral ?? '不确定'} />
        <TheoryFact
          label="可能功能"
          value={
            theory.functions.length
              ? theory.functions.map((item) => functionLabels[item] ?? item).join(' · ')
              : '不确定'
          }
        />
      </dl>
      {theory.limitations.length ? (
        <p className="theory-limitations">
          限制：{theory.limitations.join(' · ')}
        </p>
      ) : null}
      <p className="algorithm-note">
        来源：<code>{theory.algorithm}</code>
      </p>
    </section>
  )
}

function TheoryFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}
