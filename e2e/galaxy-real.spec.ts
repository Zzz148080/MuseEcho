import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { uploadAndWait } from './support'

test('real uploaded audio reaches the blue purple galaxy and colored piano on all layouts', async ({
  page,
}) => {
  // Reuse the same c-g-am-f.wav as the previous acceptance run; no route mocks.
  const evidence = path.resolve(
    process.env.MUSEECHO_UI_EVIDENCE || 'docs/evidence/frontend-mist-blue',
  )
  fs.mkdirSync(evidence, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await page.setViewportSize({ width: 1440, height: 1000 })
  const analysisId = await uploadAndWait(page)
  const audio = page.locator('audio')
  const originalMedia = await audio.elementHandle()
  await page.locator('.player-play').click()
  await expect
    .poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeGreaterThan(0.1)
  await page.locator('.player-play').click()
  await page.getByRole('slider', { name: '音频播放进度' }).fill('2')
  await expect
    .poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeCloseTo(2, 0)
  await page
    .getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /结构地图/ })
    .click()
  await page.getByRole('slider', { name: '时间轴缩放' }).fill('2')
  await expect(page.getByLabel('当前缩放倍率')).toHaveText('2.00×')
  await page.getByRole('slider', { name: '时间轴缩放' }).fill('1')
  await page
    .getByRole('button', { name: /和弦 C，/ })
    .first()
    .click()
  const notes = page.locator('.chord-orbit__note')
  await expect(notes).toHaveCount(3)
  const colors = await notes.evaluateAll((elements) =>
    elements.map((el) => getComputedStyle(el).backgroundColor),
  )
  expect(new Set(colors).size).toBe(3)
  for (const pitch of ['C', 'E', 'G']) {
    const note = page.getByRole('button', {
      name: new RegExp(`组成音 ${pitch}，`),
    })
    await note.hover({ force: true })
    await expect(page.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    await expect(page.getByRole('tooltip')).toBeVisible()
    await note.click()
    await expect(note).toHaveAttribute('aria-pressed', 'true')
    await expect(
      page.locator(
        `.chord-piano__key[data-chord-tone="true"][data-pitch="${pitch}"]`,
      ),
    ).toHaveAttribute('data-active', 'true')
    const noteColor = await note.evaluate((el) =>
      getComputedStyle(el).getPropertyValue('--tone-accent').trim(),
    )
    expect(
      await page
        .locator(
          `.chord-piano__key[data-chord-tone="true"][data-pitch="${pitch}"]`,
        )
        .evaluate((el) =>
          getComputedStyle(el).getPropertyValue('--tone-accent').trim(),
        ),
    ).toBe(noteColor)
    expect(
      await page
        .locator('.tone-education')
        .evaluate((el) =>
          getComputedStyle(el).getPropertyValue('--tone-accent').trim(),
        ),
    ).toBe(noteColor)
    await expect(page.getByText('此设备暂不支持试听')).toHaveCount(0)
  }
  // Normal-motion hover and clicks are exercised above. Freeze the layout via
  // the supported accessibility preference for deterministic resize evidence.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  for (const viewport of [
    { width: 1440, height: 1000 },
    { width: 768, height: 1024 },
    { width: 600, height: 900 },
    { width: 599, height: 900 },
    { width: 390, height: 844 },
    { width: 320, height: 740 },
  ]) {
    await page.setViewportSize(viewport)
    const detail = page.locator('.workspace-detail')
    await expect(detail).toBeVisible()
    await expect(page.getByTestId('chord-orbit')).toBeVisible()
    const rootNote = page.getByRole('button', { name: '组成音 C，根音' })
    await rootNote.click()
    await expect(rootNote).toHaveAttribute('aria-pressed', 'true')
    // The selected inner note must leave the central label unobscured.
    await expect
      .poll(async () => {
        const centre = await page.locator('.chord-orbit__centre').boundingBox()
        const note = await rootNote.boundingBox()
        if (!centre || !note) return -1
        return (
          Math.hypot(
            centre.x + centre.width / 2 - note.x - note.width / 2,
            centre.y + centre.height / 2 - note.y - note.height / 2,
          ) -
          (centre.width + note.width) / 2
        )
      })
      .toBeGreaterThan(0)
    const overflow = await detail.evaluate((el) => ({
      width: el.clientWidth,
      scroll: el.scrollWidth,
    }))
    expect(overflow, JSON.stringify(overflow)).toMatchObject({
      scroll: overflow.width,
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    expect(
      await originalMedia?.evaluate(
        (el) => el === document.querySelector('audio'),
      ),
    ).toBe(true)
    await expect(audio).toHaveCount(1)
    await detail.evaluate((el) => {
      el.scrollTop = 0
    })
    await detail.screenshot({
      path: path.join(evidence, `real-galaxy-${viewport.width}.png`),
      animations: 'disabled',
    })
  }
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await expect(page.locator('.app-shell')).not.toHaveAttribute('inert', '')
  await page
    .getByRole('button', { name: /和弦 C，/ })
    .first()
    .click()
  await expect(page.getByText('选择一个组成音')).toBeVisible()
  await expect(
    page.locator('.chord-piano__key[data-active="true"]'),
  ).toHaveCount(0)
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
  await expect(audio).toHaveCount(1)
  expect(errors).toEqual([])
  fs.writeFileSync(
    path.join(evidence, 'real-galaxy-run.json'),
    JSON.stringify(
      {
        analysisId,
        fixture: 'tmp/e2e-fixtures/c-g-am-f.wav',
        pipeline: 'real backend',
        viewports: [1440, 768, 600, 599, 390, 320],
        noteColors: colors,
        browserErrors: errors,
        checkedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
  )
})
