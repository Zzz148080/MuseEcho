import { expect, test } from '@playwright/test'
import { uploadAndWait } from './support'

test('desktop, tablet, and mobile layouts stay readable and keyboard operable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await uploadAndWait(page)
  const audio = page.locator('audio')
  await expect(audio).toHaveCount(1)
  const initialAudio = await audio.elementHandle()
  expect(initialAudio).not.toBeNull()

  const expectPersistentAudio = async () => {
    await expect(audio).toHaveCount(1)
    expect(
      await page.evaluate(
        (mountedAudio) =>
          mountedAudio?.isConnected && document.querySelector('audio') === mountedAudio,
        initialAudio,
      ),
    ).toBe(true)
    await audio.scrollIntoViewIfNeeded()
    await expect(audio).toBeVisible()
  }

  for (const viewport of [
    { width: 1440, height: 900, stacked: false },
    { width: 768, height: 1024, stacked: true },
    { width: 390, height: 844, stacked: true },
  ]) {
    await page.setViewportSize(viewport)
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)

    await expectPersistentAudio()
    const navigation = page.getByRole('navigation', { name: '分析功能' })
    const navBox = await navigation.boundingBox()
    expect(navBox).not.toBeNull()
    if (!navBox) continue

    if (viewport.width <= 599) {
      expect(navBox.y + navBox.height).toBeGreaterThanOrEqual(viewport.height - 4)
    } else {
      expect(navBox.y).toBeGreaterThanOrEqual(0)
    }

    const audioPlayer = await page.locator('.audio-player').boundingBox()
    const musicDna = await page.locator('.music-dna').boundingBox()
    const retention = await page.locator('.retention-panel').boundingBox()
    expect(audioPlayer).not.toBeNull()
    expect(musicDna).not.toBeNull()
    expect(retention).not.toBeNull()
    if (!audioPlayer || !musicDna || !retention) continue
    if (viewport.stacked) {
      expect(musicDna.y).toBeGreaterThan(audioPlayer.y + audioPlayer.height - 2)
      expect(Math.abs(musicDna.x - audioPlayer.x)).toBeLessThanOrEqual(2)
    } else {
      expect(Math.abs(musicDna.y - audioPlayer.y)).toBeLessThanOrEqual(2)
      expect(musicDna.x).toBeGreaterThan(audioPlayer.x + audioPlayer.width - 2)
    }
    expect(retention.y).toBeGreaterThan(
      Math.max(
        audioPlayer.y + audioPlayer.height,
        musicDna.y + musicDna.height,
      ) - 2,
    )

    await page.getByRole('button', { name: /结构地图/ }).click()
    await expect(page.getByRole('heading', { name: '结构地图' })).toBeVisible()
    await expectPersistentAudio()
    await page.getByRole('button', { name: /深入分析/ }).click()
    await expect(page.getByRole('heading', { name: '深入分析' })).toBeVisible()
    await expectPersistentAudio()
    await page.getByRole('button', { name: /歌曲概览/ }).click()
    await expect(page.getByRole('heading', { name: '播放器' })).toBeVisible()
    await expectPersistentAudio()
  }

  await page.getByRole('button', { name: /结构地图/ }).click()
  const start = page.getByRole('slider', { name: '片段开始' })
  await start.scrollIntoViewIfNeeded()
  await start.focus()
  await start.press('ArrowRight')
  await expect(page.getByTestId('selection')).toBeVisible()
  await expect(page.getByRole('button', { name: '清除选区' })).toBeEnabled()
  await expect(page.getByRole('button', { name: /和弦 C/ }).first()).toBeVisible()
})
