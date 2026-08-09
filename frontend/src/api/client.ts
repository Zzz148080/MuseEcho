import {
  analysisStages,
  type AnalysisStage,
  type AnalysisStatus,
  type ApiErrorBody,
  type SourceKind,
  type UploadAccepted,
} from './types'

const analysisIdPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const stageSet = new Set<string>(analysisStages)
const sourceKinds = new Set<string>(['real', 'demo', 'synthetic_test'])
const stableCodePattern = /^[a-z][a-z0-9_]{0,49}$/
const versionPattern = /^[a-z0-9][a-z0-9._-]{0,79}$/i

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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
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
