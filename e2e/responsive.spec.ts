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

  const expectNoPageOverflow = async () => {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(0)
  }

  for (const viewport of [
    { width: 1440, height: 900, stacked: false },
    { width: 1024, height: 768, stacked: false },
    { width: 768, height: 1024, stacked: true },
    { width: 390, height: 844, stacked: true },
    { width: 320, height: 568, stacked: true },
  ]) {
    await page.setViewportSize(viewport)
    await expectPersistentAudio()
    await expectNoPageOverflow()
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
    await expectNoPageOverflow()

    const chordControl = page.getByRole('button', { name: /和弦 C/ }).first()
    if (viewport.width <= 599) {
      const chordBox = await chordControl.boundingBox()
      expect(chordBox).not.toBeNull()
      if (!chordBox) throw new Error('mobile chord event has no layout box')
      expect(chordBox.width).toBeGreaterThanOrEqual(44)
      expect(chordBox.height).toBeGreaterThanOrEqual(44)
    }
    await chordControl.click()
    const detail =
      viewport.width <= 599
        ? page.getByRole('dialog', { name: /和弦/ })
        : page.getByRole('complementary', { name: '当前和弦详情' })
    await expect(detail).toBeVisible()
    const returnButton = page.getByRole('button', { name: '返回结构地图' })
    await expect(returnButton).toBeFocused()
    await expectNoPageOverflow()
    if (viewport.width <= 599) {
      await expect(detail).toHaveAttribute('aria-modal', 'true')
      await expect(page.locator('.app-shell')).toHaveAttribute('inert', '')
      const detailBox = await detail.boundingBox()
      expect(detailBox).not.toBeNull()
      if (!detailBox) throw new Error('mobile detail has no layout box')
      expect(detailBox.x).toBeLessThanOrEqual(2)
      expect(detailBox.y).toBeLessThanOrEqual(2)
      expect(detailBox.width).toBeGreaterThanOrEqual(viewport.width - 4)
      expect(detailBox.height).toBeGreaterThanOrEqual(viewport.height - 4)
      await page.keyboard.press('Tab')
      await expect(returnButton).toBeFocused()
    } else {
      await expect(detail).not.toHaveAttribute('aria-modal')
      await expect(page.locator('.app-shell')).not.toHaveAttribute('inert')
    }
    await returnButton.click()
    await expect(chordControl).toBeFocused()
    await expect(chordControl).toHaveAttribute('aria-pressed', 'true')

    await page.getByRole('button', { name: /深入分析/ }).click()
    await expect(page.getByRole('heading', { name: '深入分析' })).toBeVisible()
    await expectPersistentAudio()
    await expectNoPageOverflow()
    await page.getByRole('button', { name: /歌曲概览/ }).click()
    await expect(page.getByRole('heading', { name: '播放器' })).toBeVisible()
    await expectPersistentAudio()
    await expectNoPageOverflow()
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
