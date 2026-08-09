import type { ConfidenceLevel } from '../components/ConfidenceBadge'

export function confidenceLevel(confidence: number | null): ConfidenceLevel {
  if (confidence === null || !Number.isFinite(confidence) || confidence < 0.6) {
    return 'unknown'
  }
  return confidence >= 0.85 ? 'high' : 'medium'
}

export function isUsableConfidence(confidence: number | null): boolean {
  return confidenceLevel(confidence) !== 'unknown'
}
