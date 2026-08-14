import type { EvidenceResult } from '../../api/types'
import { formatTime } from '../timeline/Timeline'

const kindLabels: Record<string, string> = {
  chord: '和弦',
  deterministic_theory: '确定性乐理',
  energy: '动态强弱',
  rhythm: '节奏',
  section: '结构段落',
  tonality: '调性',
}

export interface EvidenceListProps {
  evidence: EvidenceResult[]
  evidenceIds: string[]
  onSelect: (evidence: EvidenceResult) => void
}

export function EvidenceList({ evidence, evidenceIds, onSelect }: EvidenceListProps) {
  const cited = evidenceIds
    .map((id) =>
      evidence.find((item) => item.id === id && item.eligible_for_llm),
    )
    .filter((item): item is EvidenceResult => item !== undefined)

  if (!cited.length) {
    return <p className="evidence-list__empty">当前回答没有可引用的合格 Evidence，结论保持 unknown。</p>
  }

  return (
    <ol className="evidence-list" aria-label="回答引用的 Evidence">
      {cited.map((item) => (
        <li key={item.id}>
          <a
            href="#timeline-title"
            onClick={(event) => {
              event.preventDefault()
              onSelect(item)
              document.getElementById('timeline-title')?.scrollIntoView?.({
                behavior: 'smooth',
                block: 'start',
              })
            }}
          >
            证据：{kindLabels[item.kind] ?? item.kind}，{formatTime(item.start_seconds)}–{formatTime(item.end_seconds)}
          </a>
          <span>置信度 {item.confidence.toFixed(2)} · {item.algorithm}</span>
        </li>
      ))}
    </ol>
  )
}
