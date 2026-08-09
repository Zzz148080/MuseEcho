import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page } from '@playwright/test'

export const fixturePath = path.resolve('tmp/e2e-fixtures/c-g-am-f.wav')

const sampleRate = 22_050
const secondsPerChord = 1
const chordFrequencies = [
  [261.6256, 329.6276, 391.9954],
  [195.9977, 246.9417, 293.6648],
  [220, 261.6256, 329.6276],
  [174.6141, 220, 261.6256],
]

export function ensureChordProgressionFixture(): void {
  const frameCount = sampleRate * secondsPerChord * chordFrequencies.length
  const payloadBytes = frameCount * 2
  const wav = Buffer.alloc(44 + payloadBytes)
  wav.write('RIFF', 0)
  wav.writeUInt32LE(36 + payloadBytes, 4)
  wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16)
  wav.writeUInt16LE(1, 20)
  wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(sampleRate, 24)
  wav.writeUInt32LE(sampleRate * 2, 28)
  wav.writeUInt16LE(2, 32)
  wav.writeUInt16LE(16, 34)
  wav.write('data', 36)
  wav.writeUInt32LE(payloadBytes, 40)

  for (let frame = 0; frame < frameCount; frame += 1) {
    const chordIndex = Math.floor(frame / (sampleRate * secondsPerChord))
    const withinChord = frame % (sampleRate * secondsPerChord)
    const edge = Math.min(withinChord, sampleRate - withinChord - 1)
    const fade = Math.min(1, Math.max(0, edge / (sampleRate * 0.02)))
    const mixed = chordFrequencies[chordIndex].reduce(
      (total, frequency) =>
        total + Math.sin((2 * Math.PI * frequency * withinChord) / sampleRate),
      0,
    )
    wav.writeInt16LE(Math.round((mixed / 3) * fade * 22_000), 44 + frame * 2)
  }

  fs.mkdirSync(path.dirname(fixturePath), { recursive: true })
  fs.writeFileSync(fixturePath, wav)
}

export async function uploadAndWait(page: Page): Promise<string> {
  ensureChordProgressionFixture()
  await page.goto('/')
  await page.getByLabel('音频文件').setInputFiles(fixturePath)
  await page.getByRole('checkbox', { name: /有权分析/ }).check()
  await page.getByRole('checkbox', { name: /加密保留最长 24 小时/ }).check()
  const uploadResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/analyses') &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /开始分析/ }).click()
  const payload = (await (await uploadResponse).json()) as { analysis_id?: unknown }
  if (typeof payload.analysis_id !== 'string') {
    throw new Error('upload response did not contain an analysis id')
  }
  await expect(page.getByText('分析完成')).toBeVisible({ timeout: 90_000 })
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
  return payload.analysis_id
}

export async function selectTimelineSegment(page: Page): Promise<void> {
  const selectionSurface = page.getByTestId('selection-surface')
  await selectionSurface.scrollIntoViewIfNeeded()
  const selectionBox = await selectionSurface.boundingBox()
  if (!selectionBox) throw new Error('selection surface has no layout box')
  await page.mouse.move(
    selectionBox.x + selectionBox.width * 0.1,
    selectionBox.y + selectionBox.height / 2,
  )
  await page.mouse.down()
  await page.mouse.move(
    selectionBox.x + selectionBox.width * 0.9,
    selectionBox.y + selectionBox.height / 2,
  )
  await page.mouse.up()
  await expect(page.getByTestId('selection')).toBeVisible()
}
