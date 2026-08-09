import type { AnalysisResult } from '../api/types'

export const analysisId = '00000000-0000-4000-8000-000000000001'

export const fixtureResult: AnalysisResult = {
  analysis_id: analysisId,
  source_kind: 'synthetic_test',
  pipeline_version: 'museecho-analysis-v1',
  track: {
    duration_seconds: 12,
    sample_rate: 44_100,
    channels: 1,
    bpm: 120,
    bpm_confidence: 0.91,
    key_tonic: 'C',
    mode: 'major',
    key_confidence: 0.88,
    time_signature: null,
    time_signature_confidence: null,
    summary: {
      source_kind: 'synthetic_test',
      pipeline_version: 'museecho-analysis-v1',
      signal_version: 'signal-features-v1',
      waveform: {
        resolution_seconds: 3,
        minimums: [-0.8, -0.4, -0.7, -0.3],
        maximums: [0.7, 0.5, 0.9, 0.4],
        algorithm: 'waveform-minmax-v1',
      },
      beat_positions_seconds: [0, 0.5, 1, 1.5],
      energy_changes: [
        {
          timestamp_seconds: 6,
          direction: 'rise',
          magnitude: 0.4,
          confidence: 0.82,
          algorithm: 'energy-change-v1',
        },
      ],
    },
  },
  sections: [
    {
      id: '00000000-0000-4000-8000-000000000011',
      start_seconds: 0,
      end_seconds: 6,
      label: 'A',
      confidence: 0.9,
      algorithm: 'structure-v1',
    },
    {
      id: '00000000-0000-4000-8000-000000000012',
      start_seconds: 6,
      end_seconds: 12,
      label: 'B',
      confidence: 0.78,
      algorithm: 'structure-v1',
    },
  ],
  chords: [
    {
      id: '00000000-0000-4000-8000-000000000021',
      start_seconds: 0,
      end_seconds: 8,
      symbol: 'C',
      confidence: 0.92,
      algorithm: 'chords-v1',
      theory: null,
    },
    {
      id: '00000000-0000-4000-8000-000000000022',
      start_seconds: 8,
      end_seconds: 12,
      symbol: 'G',
      confidence: 0.89,
      algorithm: 'chords-v1',
      theory: {
        symbol: 'G',
        tonic: 'C',
        mode: 'major',
        pitch_classes: ['G', 'B', 'D'],
        intervals: ['root', 'major third', 'perfect fifth'],
        quality: 'major',
        roman_numeral: 'V',
        functions: ['dominant'],
        is_diatonic: true,
        enharmonic_candidates: [],
        limitations: [],
        algorithm: 'deterministic-triad-theory-v1',
      },
    },
  ],
  time_series: [
    {
      kind: 'energy',
      resolution_seconds: 3,
      points: [0.2, 0.5, 0.8, 0.4],
      algorithm: 'rms-v1',
    },
  ],
  evidence: [],
}
