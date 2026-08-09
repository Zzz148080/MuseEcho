export type ConfidenceLevel = 'high' | 'medium' | 'unknown'

const confidenceLabels: Record<ConfidenceLevel, string> = {
  high: '高置信',
  medium: '中置信',
  unknown: '证据不足',
}

export interface ConfidenceBadgeProps {
  level: ConfidenceLevel
}

export function ConfidenceBadge({ level }: ConfidenceBadgeProps) {
  return (
    <span className="confidence-badge" data-confidence={level}>
      {confidenceLabels[level]}
    </span>
  )
}
