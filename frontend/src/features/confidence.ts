import type { ConfidenceLevel } from '../components/ConfidenceBadge'

export function confidenceLevel(confidence: number | null): ConfidenceLevel {
  if (confidence === null || !Number.isFinite(confidence) || confidence < 0.5) {
    return 'unknown'
  }
  if (confidence >= 0.85) return 'high'
  return confidence >= 0.7 ? 'medium' : 'low'
}

export function isUsableConfidence(confidence: number | null): boolean {
  return confidenceLevel(confidence) !== 'unknown'
}
