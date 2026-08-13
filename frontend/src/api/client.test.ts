import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  createExplanation,
  deleteAnalysis,
  getAnalysisResult,
  getAnalysisStatus,
  uploadAnalysis,
} from './client'
import type { AnalysisStatus, UploadAccepted } from './types'
import { fixtureResult } from '../test/analysisFixture'

const analysisId = '00000000-0000-4000-8000-000000000001'
const accepted: UploadAccepted = {
  analysis_id: analysisId,
  stage: 'queued',
  progress: 0,
}
const serverStatus: AnalysisStatus = {
  analysis_id: analysisId,
  status: 'queued',
  stage: 'queued',
  progress: 0,
  error_code: null,
  expires_at: '2026-08-10T00:00:00+00:00',
  pipeline_version: 'museecho-analysis-v1',
  source_kind: 'real',
}

afterEach(() => {
  vi.unstubAllGlobals()
  document.cookie = 'museecho_csrf=; Max-Age=0; Path=/'
})

describe('API client', () => {
  it('double-submits the readable CSRF cookie for explanation and deletion', async () => {
    document.cookie = 'museecho_csrf=csrf-test-token; Path=/'
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          mode: 'fallback',
          text: '只使用引用证据。',
          evidence_ids: ['00000000-0000-4000-8000-000000000031'],
        }),
      })
      .mockResolvedValueOnce({ ok: true, status: 204 })
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      createExplanation(analysisId, {
        question: '为什么这里有张力？',
        start_seconds: 8,
        end_seconds: 12,
      }),
    ).resolves.toMatchObject({ mode: 'fallback' })
    await expect(deleteAnalysis(analysisId)).resolves.toBeUndefined()

    for (const [, request] of fetchMock.mock.calls) {
      expect(request).toEqual(
        expect.objectContaining({
          credentials: 'same-origin',
          headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-test-token' }),
        }),
      )
    }
  })

  it('rejects an LLM explanation without cited Evidence', async () => {
    document.cookie = 'museecho_csrf=csrf-test-token; Path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          mode: 'llm',
          text: '没有引用的生成式回答。',
          evidence_ids: [],
        }),
      }),
    )

    await expect(
      createExplanation(analysisId, {
        question: '为什么？',
        start_seconds: 0,
        end_seconds: 1,
      }),
    ).rejects.toMatchObject({ code: 'invalid_server_response' })
  })

  it('loads an analysis result with its capability cookie', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(fixtureResult),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getAnalysisResult(analysisId)).resolves.toEqual(fixtureResult)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/analyses/${analysisId}`,
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('accepts deterministic theory using a double accidental pitch class', async () => {
    const result = structuredClone(fixtureResult)
    const theory = result.chords[1].theory
    if (!theory) throw new Error('fixture theory missing')
    theory.pitch_classes = ['A#', 'C##', 'E#']
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(result),
      }),
    )

    await expect(getAnalysisResult(analysisId)).resolves.toEqual(result)
  })

  it('rejects result identity or timeline intervals outside the track', async () => {
    const invalid = structuredClone(fixtureResult)
    invalid.chords[1].end_seconds = 13
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(invalid),
      }),
    )

    await expect(getAnalysisResult(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })

    const wrongIdentity = {
      ...fixtureResult,
      analysis_id: '00000000-0000-4000-8000-000000000002',
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(wrongIdentity),
      }),
    )
    await expect(getAnalysisResult(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('rejects malformed or non-finite visualization series', async () => {
    const malformed = structuredClone(fixtureResult)
    if (!malformed.track.summary) throw new Error('fixture summary missing')
    malformed.track.summary.waveform.maximums.pop()
    malformed.time_series[0].points[1] = Number.NaN
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(malformed),
      }),
    )

    await expect(getAnalysisResult(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('rejects incomplete deterministic theory for a known chord', async () => {
    const malformed = structuredClone(fixtureResult)
    const theory = malformed.chords[1].theory
    if (!theory) throw new Error('fixture theory missing')
    theory.pitch_classes = []
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve(malformed),
      }),
    )

    await expect(getAnalysisResult(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('sends the capability cookie and validates status responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(serverStatus),
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(getAnalysisStatus(analysisId)).resolves.toEqual(serverStatus)
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/analyses/${analysisId}/status`,
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })

  it('rejects contradictory status and stage values as an invalid response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ ...serverStatus, status: 'complete' }),
      }),
    )

    await expect(getAnalysisStatus(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('rejects a status response for a different analysis id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            ...serverStatus,
            analysis_id: '00000000-0000-4000-8000-000000000002',
          }),
      }),
    )

    await expect(getAnalysisStatus(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('accepts only the queued zero-progress contract after upload', async () => {
    const requests: FakeRequest[] = []
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends FakeRequest {
        constructor() {
          super()
          requests.push(this)
        }
      },
    )
    const promise = uploadAnalysis(
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
      vi.fn(),
    )
    requests[0].status = 202
    requests[0].response = { ...accepted, stage: 'complete', progress: 1 }
    requests[0].dispatchEvent(new Event('load'))

    await expect(promise).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('rejects unbounded or malformed stable status codes', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            ...serverStatus,
            status: 'failed',
            stage: 'failed',
            error_code: `bad path ${'x'.repeat(100)}`,
          }),
      }),
    )

    await expect(getAnalysisStatus(analysisId)).rejects.toMatchObject({
      code: 'invalid_server_response',
    })
  })

  it('reports only measurable XHR upload bytes and keeps credentials enabled', async () => {
    const requests: FakeRequest[] = []
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends FakeRequest {
        constructor() {
          super()
          requests.push(this)
        }
      },
    )
    const onProgress = vi.fn()
    const promise = uploadAnalysis(
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
      onProgress,
    )
    const request = requests[0]

    expect(request.withCredentials).toBe(true)
    expect(request.method).toBe('POST')
    expect(request.url).toBe('/api/analyses')
    expect(request.body).toBeInstanceOf(FormData)

    request.upload.dispatchEvent(
      new ProgressEvent('progress', {
        lengthComputable: true,
        loaded: 1,
        total: 4,
      }),
    )
    request.status = 202
    request.response = accepted
    request.dispatchEvent(new Event('load'))

    await expect(promise).resolves.toEqual(accepted)
    expect(onProgress.mock.calls.map(([value]) => value)).toEqual([0.25, 1])
  })

  it('does not expose server messages through its public error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: () =>
          Promise.resolve({
            error: { code: 'invalid_audio', message: 'sensitive path detail' },
          }),
      }),
    )

    const error = await getAnalysisStatus(analysisId).catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'invalid_audio', status: 422 })
    expect(String(error)).not.toContain('sensitive path detail')
  })
})

class FakeRequest extends EventTarget {
  readonly upload = new EventTarget()
  body: Document | XMLHttpRequestBodyInit | null = null
  method = ''
  response: unknown = null
  responseType: XMLHttpRequestResponseType = ''
  status = 0
  url = ''
  withCredentials = false

  open(method: string, url: string) {
    this.method = method
    this.url = url
  }

  setRequestHeader() {
    return undefined
  }

  send(body: Document | XMLHttpRequestBodyInit | null) {
    this.body = body
  }
}
