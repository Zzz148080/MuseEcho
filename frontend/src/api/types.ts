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
