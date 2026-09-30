import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { uploadAndWait } from './support'

test('integrated real workbench keeps playback, context links and the map together', async ({
  page,
}) => {
  const evidence = path.resolve('docs/evidence/frontend-workbench')
  fs.mkdirSync(evidence, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await uploadAndWait(page)
  await page.evaluate(() => document.fonts.ready)
  expect(
    await page.evaluate(() =>
      ['Noto Sans SC', 'Manrope', 'IBM Plex Mono'].every((family) =>
        document.fonts.check(`16px "${family}"`),
      ),
    ),
  ).toBe(true)
  const audio = page.locator('audio')
  const original = await audio.elementHandle()
  await expect(page.locator('.analysis-receipt')).not.toHaveAttribute(
    'open',
    '',
  )
  await page.locator('.analysis-receipt summary').click()
  await expect(page.locator('.analysis-receipt__body')).toBeVisible()
  await page.locator('.analysis-receipt summary').click()
  const nav = page.getByRole('navigation', { name: '分析功能' })
  await page.locator('.player-play').click()
  for (const name of [/结构地图/, /深入分析/, /歌曲概览/]) {
    await nav.getByRole('button', { name }).click()
    expect(await audio.evaluate((el: HTMLAudioElement) => el.paused)).toBe(
      false,
    )
    expect(
      await original?.evaluate((el) => el === document.querySelector('audio')),
    ).toBe(true)
  }
  await page.locator('.player-play').click()
  await page.getByRole('slider', { name: '音频播放进度' }).fill('0')
  await page.getByRole('button', { name: '探索当前和弦' }).click()
  await expect(page.getByTestId('chord-orbit')).toBeVisible()
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await expect(page.getByRole('button', { name: '探索当前和弦' })).toBeFocused()
  const player = await page.locator('.audio-player').boundingBox()
  const map = await page.locator('.workspace-view--map').boundingBox()
  expect(player).not.toBeNull()
  expect(map).not.toBeNull()
  expect(Math.abs(player!.width - map!.width)).toBeLessThan(2)
  expect(map!.y - player!.y - player!.height).toBeLessThan(32)
  await page.evaluate(() => window.scrollTo(0, 0))
  expect(
    (await page.locator('.timeline__frame').boundingBox())!.y,
  ).toBeLessThan(650)
  await page.getByRole('slider', { name: '时间轴缩放' }).fill('3')
  await page.getByRole('button', { name: /全曲视野/ }).click()
  await expect(page.getByLabel('当前缩放倍率')).toHaveText('1.00×')
  await page.getByRole('slider', { name: '片段开始' }).fill('1')
  await expect(page.locator('.timeline__selection-duration')).toHaveText(
    '时长 3.0 秒',
  )
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, 'real-workbench-desktop.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({
    path: path.join(evidence, 'real-workbench-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.getByRole('button', { name: '探索当前和弦' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await expect(page.getByRole('button', { name: '探索当前和弦' })).toBeFocused()
  expect(
    await original?.evaluate((el) => el === document.querySelector('audio')),
  ).toBe(true)
  expect(errors).toEqual([])
})
