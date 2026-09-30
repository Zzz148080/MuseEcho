import fs from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { uploadAndWait } from './support'

test('real analysis follows the overview to map to detail path on desktop and phone', async ({
  page,
}) => {
  const evidence = path.resolve('docs/evidence/frontend-enhanced')
  fs.mkdirSync(evidence, { recursive: true })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await uploadAndWait(page)
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
  const audio = page.locator('audio')
  const original = await audio.elementHandle()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.screenshot({
    path: path.join(evidence, 'real-overview-desktop.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: /沿时间轴继续/ }).click()
  await expect(page.getByRole('heading', { name: '结构地图' })).toBeVisible()
  await expect(
    page
      .getByRole('navigation', { name: '分析功能' })
      .getByRole('button', { name: /结构地图/ }),
  ).toHaveAttribute('aria-current', 'page')
  expect(
    await original?.evaluate((el) => el === document.querySelector('audio')),
  ).toBe(true)
  await page
    .getByRole('button', { name: /和弦 C，/ })
    .first()
    .click()
  await expect(page.getByTestId('chord-orbit')).toBeVisible()
  await expect(page.locator('.chord-piano')).toBeVisible()
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await page
    .getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /深入分析/ })
    .click()
  await expect(page.getByRole('heading', { name: '深入分析' })).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await page
    .getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /歌曲概览/ })
    .click()
  await expect(page.getByRole('button', { name: /沿时间轴继续/ })).toBeVisible()
  await page.screenshot({
    path: path.join(evidence, 'real-overview-mobile.png'),
    fullPage: true,
    animations: 'disabled',
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await page.getByRole('button', { name: /沿时间轴继续/ }).click()
  await expect(page.getByRole('heading', { name: '结构地图' })).toBeVisible()
  expect(
    await original?.evaluate((el) => el === document.querySelector('audio')),
  ).toBe(true)
  expect(errors).toEqual([])
})
