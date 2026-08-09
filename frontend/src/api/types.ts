export const analysisStages = [
  'queued',
  'validating',
  'decoding',
  'rhythm',
  'tonality',
  'structure',
  'chords',
  'evidence',
  'complete',
  'failed',
  'deleted',
  'expired',
] as const

export type AnalysisStage = (typeof analysisStages)[number]
export type SourceKind = 'real' | 'demo' | 'synthetic_test'

export interface UploadAccepted {
  analysis_id: string
  stage: AnalysisStage
  progress: number
}

export interface AnalysisStatus {
  analysis_id: string
  status: AnalysisStage
  stage: AnalysisStage
  progress: number
  error_code: string | null
  expires_at: string | null
  pipeline_version: string | null
  source_kind: SourceKind
}

export interface ApiErrorBody {
  error?: {
    code?: unknown
    message?: unknown
  }
}

export interface WaveformSummary {
  resolution_seconds: number
  minimums: number[]
  maximums: number[]
  algorithm: string
}

export interface EnergyChangeSummary {
  timestamp_seconds: number
  direction: 'rise' | 'fall'
  magnitude: number
  confidence: number
  algorithm: string
}

export interface TrackSummary {
  source_kind: SourceKind
  pipeline_version: string
  signal_version: string
  waveform: WaveformSummary
  beat_positions_seconds: number[]
  energy_changes: EnergyChangeSummary[]
}

export interface TrackResult {
  duration_seconds: number
  sample_rate: number
  channels: number
  bpm: number | null
  bpm_confidence: number | null
  key_tonic: string | null
  mode: 'major' | 'minor' | null
  key_confidence: number | null
  time_signature: string | null
  time_signature_confidence: number | null
  summary: TrackSummary | null
}

export interface SectionResult {
  id: string
  start_seconds: number
  end_seconds: number
  label: string
  confidence: number
  algorithm: string
}

export interface ChordTheoryResult {
  symbol: string
  tonic: string | null
  mode: 'major' | 'minor' | null
  pitch_classes: string[]
  intervals: string[]
  quality: 'major' | 'minor'
  roman_numeral: string | null
  functions: string[]
  is_diatonic: boolean | null
  enharmonic_candidates: string[]
  limitations: string[]
  algorithm: string
}

export interface ChordResult {
  id: string
  start_seconds: number
  end_seconds: number
  symbol: string
  confidence: number
  algorithm: string
  theory: ChordTheoryResult | null
}

export interface TimeSeriesResult {
  kind: string
  resolution_seconds: number
  points: number[]
  algorithm: string
}

export interface EvidenceResult {
  id: string
  kind: string
  start_seconds: number
  end_seconds: number
  value: unknown
  confidence: number
  algorithm: string
  eligible_for_llm: boolean
}

export interface AnalysisResult {
  analysis_id: string
  source_kind: SourceKind
  pipeline_version: string | null
  track: TrackResult
  sections: SectionResult[]
  chords: ChordResult[]
  time_series: TimeSeriesResult[]
  evidence: EvidenceResult[]
}

export interface ExplanationRequest {
  question: string
  start_seconds: number
  end_seconds: number
}

export interface ExplanationResponse {
  mode: 'fallback' | 'llm'
  text: string
  evidence_ids: string[]
}
