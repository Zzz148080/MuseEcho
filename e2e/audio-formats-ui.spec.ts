import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { expect, test } from '@playwright/test'
import {
  ensureChordProgressionFixture,
  fixturePath,
  uploadAndWait,
} from './support'

const formats = [
  ['wav', 'pcm_s16le'],
  ['mp3', 'libmp3lame'],
  ['flac', 'flac'],
  ['m4a', 'aac'],
  ['aac', 'aac'],
  ['ogg', 'libvorbis'],
  ['opus', 'libopus'],
] as const

for (const [extension, codec] of formats) {
  test(`real ${extension} upload, analysis, playback and seek`, async ({
    page,
  }) => {
    ensureChordProgressionFixture()
    const audioPath = path.resolve(
      `tmp/e2e-fixtures/studio-${extension}.${extension}`,
    )
    execFileSync(
      'ffmpeg',
      [
        '-hide_banner',
        '-loglevel',
        'error',
        '-y',
        '-i',
        fixturePath,
        '-c:a',
        codec,
        audioPath,
      ],
      { windowsHide: true },
    )
    await uploadAndWait(page, audioPath)
    const audio = page.locator('audio')
    await expect(audio).toHaveCount(1)
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.readyState),
      )
      .toBeGreaterThanOrEqual(1)
    await page.locator('.player-play').click()
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeGreaterThan(0.1)
    await page.locator('.player-play').click()
    await expect
      .poll(() => audio.evaluate((element: HTMLAudioElement) => element.paused))
      .toBe(true)
    const slider = page.getByRole('slider', { name: '音频播放进度' })
    await slider.fill('2')
    await expect
      .poll(() =>
        audio.evaluate((element: HTMLAudioElement) => element.currentTime),
      )
      .toBeCloseTo(2, 0)
    await expect(page.getByLabel('当前播放时间')).toHaveText('0:02')
    if (extension === 'wav') {
      fs.mkdirSync('docs/evidence/frontend-mist-blue', { recursive: true })
      await page.screenshot({
        path: 'docs/evidence/frontend-mist-blue/real-pipeline-wav.png',
        fullPage: true,
        animations: 'disabled',
      })
    }
  })
}
