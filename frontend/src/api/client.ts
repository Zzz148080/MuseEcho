import {
  analysisStages,
  type AnalysisResult,
  type AnalysisStage,
  type AnalysisStatus,
  type ApiErrorBody,
  type ChordResult,
  type ChordTheoryResult,
  type EnergyChangeSummary,
  type EvidenceResult,
  type SectionResult,
  type SourceKind,
  type TimeSeriesResult,
  type TrackResult,
  type TrackSummary,
  type UploadAccepted,
  type WaveformSummary,
} from './types'

const analysisIdPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const stageSet = new Set<string>(analysisStages)
const sourceKinds = new Set<string>(['real', 'demo', 'synthetic_test'])
const stableCodePattern = /^[a-z][a-z0-9_]{0,49}$/
const versionPattern = /^[a-z0-9][a-z0-9._-]{0,79}$/i
const notePattern = /^[A-G](?:#|b)?$/
const chordPattern = /^(?:[A-G](?:#|b)?m?|unknown)$/
const labelPattern = /^(?:[A-Z]+|unknown)$/
const maximumResultItems = 5_000

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message = 'MuseEcho request failed',
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export type UploadProgressHandler = (progress: number) => void
export type UploadTransport = (
  file: File,
  onProgress: UploadProgressHandler,
) => Promise<UploadAccepted>

export function uploadAnalysis(
  file: File,
  onProgress: UploadProgressHandler,
): Promise<UploadAccepted> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', '/api/analyses')
    request.responseType = 'json'
    request.withCredentials = true
    request.setRequestHeader('Accept', 'application/json')

    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.min(1, Math.max(0, event.loaded / event.total)))
      }
    })
    request.addEventListener('error', () => {
      reject(new ApiError(0, 'network_error'))
    })
    request.addEventListener('abort', () => {
      reject(new ApiError(0, 'upload_aborted'))
    })
    request.addEventListener('load', () => {
      if (request.status < 200 || request.status >= 300) {
        reject(errorFromResponse(request.status, request.response))
        return
      }
      try {
        const accepted = parseUploadAccepted(request.response)
        onProgress(1)
        resolve(accepted)
      } catch {
        reject(new ApiError(request.status, 'invalid_server_response'))
      }
    })

    const body = new FormData()
    body.append('file', file, file.name)
    request.send(body)
  })
}

export async function getAnalysisStatus(
  analysisId: string,
): Promise<AnalysisStatus> {
  if (!analysisIdPattern.test(analysisId)) {
    throw new ApiError(0, 'invalid_analysis_id')
  }
  let response: Response
  try {
    response = await fetch(`/api/analyses/${analysisId}/status`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(0, 'network_error')
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    throw errorFromResponse(response.status, body)
  }
  try {
    const status = parseAnalysisStatus(body)
    if (status.analysis_id !== analysisId) {
      throw new TypeError('status response analysis id mismatch')
    }
    return status
  } catch {
    throw new ApiError(response.status, 'invalid_server_response')
  }
}

export async function getAnalysisResult(
  analysisId: string,
): Promise<AnalysisResult> {
  if (!analysisIdPattern.test(analysisId)) {
    throw new ApiError(0, 'invalid_analysis_id')
  }
  let response: Response
  try {
    response = await fetch(`/api/analyses/${analysisId}`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(0, 'network_error')
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw errorFromResponse(response.status, body)
  try {
    const result = parseAnalysisResult(body)
    if (result.analysis_id !== analysisId) {
      throw new TypeError('result response analysis id mismatch')
    }
    return result
  } catch {
    throw new ApiError(response.status, 'invalid_server_response')
  }
}

function errorFromResponse(status: number, body: unknown): ApiError {
  const error = (isRecord(body) ? (body as ApiErrorBody).error : undefined)
  const code =
    isRecord(error) && isStableCode(error.code)
      ? error.code
      : status === 404
        ? 'not_found'
        : 'request_failed'
  return new ApiError(status, code)
}

function parseUploadAccepted(value: unknown): UploadAccepted {
  if (
    !isRecord(value) ||
    !isAnalysisId(value.analysis_id) ||
    value.stage !== 'queued' ||
    value.progress !== 0
  ) {
    throw new TypeError('invalid upload response')
  }
  return {
    analysis_id: value.analysis_id,
    stage: value.stage,
    progress: value.progress,
  }
}

function parseAnalysisStatus(value: unknown): AnalysisStatus {
  if (
    !isRecord(value) ||
    !isAnalysisId(value.analysis_id) ||
    !isStage(value.status) ||
    !isStage(value.stage) ||
    value.status !== value.stage ||
    !isProgress(value.progress) ||
    !isValidErrorCode(value.error_code, value.stage) ||
    !isValidExpiry(value.expires_at) ||
    !isValidVersion(value.pipeline_version) ||
    !isSourceKind(value.source_kind)
  ) {
    throw new TypeError('invalid status response')
  }
  return {
    analysis_id: value.analysis_id,
    status: value.status,
    stage: value.stage,
    progress: value.progress,
    error_code: value.error_code,
    expires_at: value.expires_at,
    pipeline_version: value.pipeline_version,
    source_kind: value.source_kind,
  }
}

function parseAnalysisResult(value: unknown): AnalysisResult {
  const result = record(value)
  const analysisId = analysisIdValue(result.analysis_id)
  const sourceKind = sourceKindValue(result.source_kind)
  const pipelineVersion = nullableVersion(result.pipeline_version)
  const track = parseTrack(result.track, sourceKind, pipelineVersion)
  const sections = arrayValue(result.sections, parseSection, maximumResultItems)
  const chords = arrayValue(result.chords, parseChord, maximumResultItems)
  const timeSeries = arrayValue(result.time_series, parseTimeSeries, 32)
  const evidence = arrayValue(result.evidence, parseEvidence, maximumResultItems)
  for (const event of [...sections, ...chords, ...evidence]) {
    if (event.end_seconds > track.duration_seconds) {
      throw new TypeError('result interval exceeds track duration')
    }
  }
  return {
    analysis_id: analysisId,
    source_kind: sourceKind,
    pipeline_version: pipelineVersion,
    track,
    sections,
    chords,
    time_series: timeSeries,
    evidence,
  }
}

function parseTrack(
  value: unknown,
  sourceKind: SourceKind,
  pipelineVersion: string | null,
): TrackResult {
  const track = record(value)
  const duration = finiteNumber(track.duration_seconds, 0, 600, false)
  const sampleRate = integer(track.sample_rate, 8_000, 192_000)
  const channels = integer(track.channels, 1, 8)
  const bpm = nullableNumber(track.bpm, 1, 400)
  const bpmConfidence = nullableConfidence(track.bpm_confidence)
  const keyTonic = nullablePattern(track.key_tonic, notePattern)
  const mode = track.mode === null ? null : enumValue(track.mode, ['major', 'minor'] as const)
  const keyConfidence = nullableConfidence(track.key_confidence)
  const timeSignature = nullableBoundedString(track.time_signature, 16)
  const timeSignatureConfidence = nullableConfidence(track.time_signature_confidence)
  const summary =
    track.summary === null
      ? null
      : parseTrackSummary(track.summary, duration, sourceKind, pipelineVersion)
  return {
    duration_seconds: duration,
    sample_rate: sampleRate,
    channels,
    bpm,
    bpm_confidence: bpmConfidence,
    key_tonic: keyTonic,
    mode,
    key_confidence: keyConfidence,
    time_signature: timeSignature,
    time_signature_confidence: timeSignatureConfidence,
    summary,
  }
}

function parseTrackSummary(
  value: unknown,
  duration: number,
  sourceKind: SourceKind,
  pipelineVersion: string | null,
): TrackSummary {
  const summary = record(value)
  const parsedSource = sourceKindValue(summary.source_kind)
  const parsedPipeline = version(summary.pipeline_version)
  if (parsedSource !== sourceKind || (pipelineVersion && parsedPipeline !== pipelineVersion)) {
    throw new TypeError('summary metadata mismatch')
  }
  const beats = numberArray(summary.beat_positions_seconds, maximumResultItems, 0, duration)
  if (beats.some((item, index) => index > 0 && item < beats[index - 1])) {
    throw new TypeError('beat positions must be monotonic')
  }
  return {
    source_kind: parsedSource,
    pipeline_version: parsedPipeline,
    signal_version: version(summary.signal_version),
    waveform: parseWaveform(summary.waveform),
    beat_positions_seconds: beats,
    energy_changes: arrayValue(
      summary.energy_changes,
      (item) => parseEnergyChange(item, duration),
      maximumResultItems,
    ),
  }
}

function parseWaveform(value: unknown): WaveformSummary {
  const waveform = record(value)
  const minimums = numberArray(waveform.minimums, maximumResultItems, -1, 1, false)
  const maximums = numberArray(waveform.maximums, maximumResultItems, -1, 1, false)
  if (minimums.length !== maximums.length) {
    throw new TypeError('waveform arrays must have equal lengths')
  }
  if (minimums.some((minimum, index) => minimum > maximums[index])) {
    throw new TypeError('waveform minimum exceeds maximum')
  }
  return {
    resolution_seconds: finiteNumber(waveform.resolution_seconds, 0, 600, false),
    minimums,
    maximums,
    algorithm: version(waveform.algorithm),
  }
}

function parseEnergyChange(value: unknown, duration: number): EnergyChangeSummary {
  const item = record(value)
  return {
    timestamp_seconds: finiteNumber(item.timestamp_seconds, 0, duration),
    direction: enumValue(item.direction, ['rise', 'fall'] as const),
    magnitude: finiteNumber(item.magnitude, 0, 1),
    confidence: confidence(item.confidence),
    algorithm: version(item.algorithm),
  }
}

function parseSection(value: unknown): SectionResult {
  const item = record(value)
  const [start, end] = interval(item)
  return {
    id: analysisIdValue(item.id),
    start_seconds: start,
    end_seconds: end,
    label: pattern(item.label, labelPattern),
    confidence: confidence(item.confidence),
    algorithm: version(item.algorithm),
  }
}

function parseChord(value: unknown): ChordResult {
  const item = record(value)
  const [start, end] = interval(item)
  const symbol = pattern(item.symbol, chordPattern)
  return {
    id: analysisIdValue(item.id),
    start_seconds: start,
    end_seconds: end,
    symbol,
    confidence: confidence(item.confidence),
    algorithm: version(item.algorithm),
    theory: item.theory === null ? null : parseTheory(item.theory, symbol),
  }
}

function parseTheory(value: unknown, chordSymbol: string): ChordTheoryResult {
  const theory = record(value)
  if (chordSymbol === 'unknown') throw new TypeError('unknown chord cannot have theory')
  const symbol = pattern(theory.symbol, chordPattern)
  const pitchClasses = stringArray(theory.pitch_classes, 3, notePattern)
  const intervals = stringArray(theory.intervals, 3)
  if (
    symbol !== chordSymbol ||
    pitchClasses.length !== 3 ||
    intervals.length !== 3
  ) {
    throw new TypeError('incomplete deterministic triad theory')
  }
  return {
    symbol,
    tonic: nullablePattern(theory.tonic, notePattern),
    mode: theory.mode === null ? null : enumValue(theory.mode, ['major', 'minor'] as const),
    pitch_classes: pitchClasses,
    intervals,
    quality: enumValue(theory.quality, ['major', 'minor'] as const),
    roman_numeral: nullableBoundedString(theory.roman_numeral, 16),
    functions: stringArray(theory.functions, 8, /^[a-z][a-z-]{0,49}$/),
    is_diatonic:
      theory.is_diatonic === null ? null : booleanValue(theory.is_diatonic),
    enharmonic_candidates: stringArray(theory.enharmonic_candidates, 8, notePattern),
    limitations: stringArray(theory.limitations, 16, /^[a-z][a-z-]{0,49}$/),
    algorithm: version(theory.algorithm),
  }
}

function parseTimeSeries(value: unknown): TimeSeriesResult {
  const item = record(value)
  const kind = pattern(item.kind, stableCodePattern)
  const points = numberArray(
    item.points,
    20_000,
    kind === 'energy' ? 0 : -Number.MAX_VALUE,
    kind === 'energy' ? 1 : Number.MAX_VALUE,
  )
  return {
    kind,
    resolution_seconds: finiteNumber(item.resolution_seconds, 0, 600, false),
    points,
    algorithm: version(item.algorithm),
  }
}

function parseEvidence(value: unknown): EvidenceResult {
  const item = record(value)
  const [start, end] = interval(item)
  if (!isJsonValue(item.value)) throw new TypeError('evidence value is not safe JSON')
  return {
    id: analysisIdValue(item.id),
    kind: pattern(item.kind, stableCodePattern),
    start_seconds: start,
    end_seconds: end,
    value: item.value,
    confidence: confidence(item.confidence),
    algorithm: version(item.algorithm),
    eligible_for_llm: booleanValue(item.eligible_for_llm),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new TypeError('expected object')
  return value
}

function finiteNumber(
  value: unknown,
  minimum: number,
  maximum: number,
  inclusiveMinimum = true,
): number {
  if (
    typeof value !== 'number' ||
    !Number.isFinite(value) ||
    (inclusiveMinimum ? value < minimum : value <= minimum) ||
    value > maximum
  ) {
    throw new TypeError('number outside contract')
  }
  return value
}

function integer(value: unknown, minimum: number, maximum: number): number {
  const parsed = finiteNumber(value, minimum, maximum)
  if (!Number.isInteger(parsed)) throw new TypeError('expected integer')
  return parsed
}

function confidence(value: unknown): number {
  return finiteNumber(value, 0, 1)
}

function nullableConfidence(value: unknown): number | null {
  return value === null ? null : confidence(value)
}

function nullableNumber(value: unknown, minimum: number, maximum: number): number | null {
  return value === null ? null : finiteNumber(value, minimum, maximum)
}

function pattern(value: unknown, expected: RegExp): string {
  if (typeof value !== 'string' || !expected.test(value)) {
    throw new TypeError('string outside contract')
  }
  return value
}

function version(value: unknown): string {
  return pattern(value, versionPattern)
}

function nullableVersion(value: unknown): string | null {
  return value === null ? null : version(value)
}

function nullablePattern(value: unknown, expected: RegExp): string | null {
  return value === null ? null : pattern(value, expected)
}

function nullableBoundedString(value: unknown, maximum: number): string | null {
  if (value === null) return null
  if (typeof value !== 'string' || !value.length || value.length > maximum) {
    throw new TypeError('string outside contract')
  }
  return value
}

function analysisIdValue(value: unknown): string {
  return pattern(value, analysisIdPattern)
}

function sourceKindValue(value: unknown): SourceKind {
  if (!isSourceKind(value)) throw new TypeError('invalid source kind')
  return value
}

function enumValue<const T extends readonly string[]>(
  value: unknown,
  allowed: T,
): T[number] {
  if (typeof value !== 'string' || !allowed.includes(value)) {
    throw new TypeError('invalid enum value')
  }
  return value
}

function booleanValue(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new TypeError('expected boolean')
  return value
}

function interval(value: Record<string, unknown>): [number, number] {
  const start = finiteNumber(value.start_seconds, 0, 600)
  const end = finiteNumber(value.end_seconds, 0, 600, false)
  if (end <= start) throw new TypeError('invalid interval')
  return [start, end]
}

function arrayValue<T>(
  value: unknown,
  parse: (item: unknown) => T,
  maximum: number,
): T[] {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new TypeError('array outside contract')
  }
  return value.map(parse)
}

function numberArray(
  value: unknown,
  maximum: number,
  minimum: number,
  upper: number,
  allowEmpty = true,
): number[] {
  if (!Array.isArray(value) || value.length > maximum || (!allowEmpty && !value.length)) {
    throw new TypeError('number array outside contract')
  }
  return value.map((item) => finiteNumber(item, minimum, upper))
}

function stringArray(value: unknown, maximum: number, expected?: RegExp): string[] {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new TypeError('string array outside contract')
  }
  return value.map((item) => {
    if (typeof item !== 'string' || !item.length || item.length > 80) {
      throw new TypeError('string array item outside contract')
    }
    if (expected && !expected.test(item)) throw new TypeError('invalid string array item')
    return item
  })
}

function isJsonValue(value: unknown, depth = 0): boolean {
  if (depth > 8) return false
  if (value === null || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value === 'string') return value.length <= 10_000
  if (Array.isArray(value)) {
    return value.length <= 1_000 && value.every((item) => isJsonValue(item, depth + 1))
  }
  if (isRecord(value)) {
    const entries = Object.entries(value)
    return (
      entries.length <= 1_000 &&
      entries.every(
        ([key, item]) => key.length <= 100 && isJsonValue(item, depth + 1),
      )
    )
  }
  return false
}

function isAnalysisId(value: unknown): value is string {
  return typeof value === 'string' && analysisIdPattern.test(value)
}

function isStage(value: unknown): value is AnalysisStage {
  return typeof value === 'string' && stageSet.has(value)
}

function isProgress(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
}

function isStableCode(value: unknown): value is string {
  return typeof value === 'string' && stableCodePattern.test(value)
}

function isValidErrorCode(
  value: unknown,
  stage: AnalysisStage,
): value is string | null {
  return stage === 'failed' ? isStableCode(value) : value === null
}

function isValidExpiry(value: unknown): value is string | null {
  return (
    value === null ||
    (typeof value === 'string' &&
      value.length <= 64 &&
      Number.isFinite(Date.parse(value)))
  )
}

function isValidVersion(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && versionPattern.test(value))
}

function isSourceKind(value: unknown): value is SourceKind {
  return typeof value === 'string' && sourceKinds.has(value)
}

export { analysisIdPattern }
