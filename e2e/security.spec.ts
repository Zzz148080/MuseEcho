import fs from 'node:fs'
import crypto from 'node:crypto'
import https from 'node:https'
import { expect, request, test } from '@playwright/test'
import { uploadAndWait } from './support'

const baseUrl = 'https://127.0.0.1:4173'
const maxUploadRequestBytes = 100 * 1024 * 1024 + 64 * 1024

function postDeclaredMultipartLength(
  contentLength: number,
): Promise<{ body: string; status: number }> {
  return new Promise((resolve, reject) => {
    const upload = https.request(
      `${baseUrl}/api/analyses`,
      {
        method: 'POST',
        rejectUnauthorized: false,
        headers: {
          'content-length': String(contentLength),
          'content-type': 'multipart/form-data; boundary=museecho',
        },
      },
      (response) => {
        let body = ''
        response.setEncoding('utf8')
        response.on('data', (chunk) => (body += chunk))
        response.on('end', () =>
          resolve({ body, status: response.statusCode ?? 0 }),
        )
      },
    )
    upload.on('error', reject)
    upload.end()
  })
}

test('capability, CSRF, Range, and audit-log boundaries hold together', async ({
  page,
}) => {
  const analysisId = await uploadAndWait(page)
  const anonymous = await request.newContext({
    baseURL: baseUrl,
    ignoreHTTPSErrors: true,
  })
  const missingId = crypto.randomUUID()
  for (const suffix of ['/status', '', '/audio']) {
    const denied = await anonymous.get(`/api/analyses/${analysisId}${suffix}`)
    const missing = await anonymous.get(`/api/analyses/${missingId}${suffix}`)
    expect(denied.status()).toBe(404)
    expect(await denied.json()).toEqual(await missing.json())
  }
  await anonymous.dispose()

  const authorized = page.context().request
  const range = await authorized.get(`${baseUrl}/api/analyses/${analysisId}/audio`, {
    headers: { Range: 'bytes=0-31' },
  })
  expect(range.status()).toBe(206)
  expect(range.headers()['content-range']).toMatch(/^bytes 0-31\/\d+$/)
  expect((await range.body()).byteLength).toBe(32)

  const explanationUrl = `${baseUrl}/api/analyses/${analysisId}/explanations`
  const requestBody = {
    question: 'LOG_SENTINEL_question_body_must_not_appear',
    start_seconds: 0,
    end_seconds: 2,
  }
  for (const csrf of [undefined, 'wrong-csrf-token']) {
    const denied = await authorized.post(explanationUrl, {
      data: requestBody,
      headers: {
        Origin: baseUrl,
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
    })
    expect(denied.status()).toBe(404)
  }

  const cookies = await page.context().cookies()
  const csrf = cookies.find((cookie) => cookie.name === 'museecho_csrf')?.value
  expect(csrf).toBeTruthy()
  const accepted = await authorized.post(explanationUrl, {
    data: requestBody,
    headers: { Origin: baseUrl, 'X-CSRF-Token': csrf ?? '' },
  })
  expect(accepted.status()).toBe(200)
  expect((await authorized.get(`${baseUrl}/api/analyses/${analysisId}/status`)).status()).toBe(
    200,
  )

  const pointer = JSON.parse(
    fs.readFileSync('tmp/e2e-runtime/current-run.json', 'utf8'),
  ) as { audit_log: string }
  const auditLog = fs.readFileSync(pointer.audit_log, 'utf8')
  for (const secret of [
    requestBody.question,
    'c-g-am-f.wav',
    'museecho_access',
    'museecho_csrf',
    ...cookies.map((cookie) => cookie.value),
  ]) {
    expect(auditLog).not.toContain(secret)
  }
})

test('oversized multipart is rejected before parsing or analysis', async () => {
  const response = await postDeclaredMultipartLength(maxUploadRequestBytes + 1)

  expect(response.status).toBe(413)
  expect(JSON.parse(response.body).error.code).toBe('upload_too_large')
})
