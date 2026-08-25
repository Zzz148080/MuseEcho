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
    { width: 1023, height: 768, stacked: false },
    { width: 600, height: 900, stacked: true },
    { width: 599, height: 900, stacked: true },
    { width: 390, height: 844, stacked: true },
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
    await expect(
      page.getByRole('region', { name: '和弦事件列表' }),
    ).toHaveCount(viewport.width <= 599 ? 1 : 0)
    await expectPersistentAudio()
    await expectNoPageOverflow()

    const timelineViewport = page.getByTestId('timeline-viewport')
    const timelineContent = page.getByTestId('timeline-content')
    const beforeZoom = await timelineContent.boundingBox()
    expect(beforeZoom).not.toBeNull()
    const playback = page.getByRole('slider', { name: '播放位置' })
    const duration = Number(await playback.getAttribute('max'))
    await playback.fill(String(duration / 2))
    await page.getByRole('slider', { name: '时间轴缩放' }).fill('2.25')
    const afterZoom = await timelineContent.boundingBox()
    expect(afterZoom).not.toBeNull()
    expect(afterZoom!.width / beforeZoom!.width).toBeCloseTo(2.25, 1)
    for (const layer of ['waveform', 'sections', 'chords', 'energy', 'events']) {
      const layerBox = await timelineContent
        .locator(`[data-timeline-layer="${layer}"]`)
        .boundingBox()
      expect(layerBox).not.toBeNull()
      expect(layerBox!.width).toBeCloseTo(afterZoom!.width, 0)
    }
    const viewportGeometry = await timelineViewport.evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollLeft: element.scrollLeft,
      scrollWidth: element.scrollWidth,
    }))
    expect(viewportGeometry.scrollWidth).toBeGreaterThan(viewportGeometry.clientWidth)
    expect(viewportGeometry.scrollLeft).toBeCloseTo(
      (viewportGeometry.scrollWidth - viewportGeometry.clientWidth) / 2,
      -1,
    )
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
      viewport.width <= 1023
        ? page.getByRole('dialog', { name: /和弦/ })
        : page.getByRole('complementary', { name: '当前和弦详情' })
    await expect(detail).toBeVisible()
    const returnButton = page.getByRole('button', { name: '返回结构地图' })
    await expect(returnButton).toBeFocused()
    await expectNoPageOverflow()
    if (viewport.width <= 1023) {
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
      await expect(detail.locator('.chord-orbit__note').first()).toBeFocused()
      await page.keyboard.press('Shift+Tab')
      await expect(returnButton).toBeFocused()
    } else {
      await expect(detail).not.toHaveAttribute('aria-modal')
      await expect(page.locator('.app-shell')).not.toHaveAttribute('inert')
      const timelineBox = await page.locator('.timeline').boundingBox()
      const detailBox = await detail.boundingBox()
      expect(timelineBox).not.toBeNull()
      expect(detailBox).not.toBeNull()
      expect(detailBox!.y).toBeGreaterThanOrEqual(
        timelineBox!.y + timelineBox!.height - 2,
      )
    }

    if (viewport.width === 1440) {
      const toneButtons = detail.locator('.chord-orbit__note')
      await expect(toneButtons).toHaveCount(3)
      await detail.locator('.chord-orbit').scrollIntoViewIfNeeded()
      // Orbiting notes intentionally never become geometrically "stable", so
      // move the real pointer to the note's current centre without waiting for
      // Playwright's actionability stability gate. Mouse enter then pauses it.
      const hoverTarget = await toneButtons.nth(1).boundingBox()
      expect(hoverTarget).not.toBeNull()
      await page.mouse.move(
        hoverTarget!.x + hoverTarget!.width / 2,
        hoverTarget!.y + hoverTarget!.height / 2,
      )
      const tooltip = detail.getByRole('tooltip')
      await expect(tooltip).toBeVisible()
      const tooltipBox = await tooltip.boundingBox()
      expect(tooltipBox).not.toBeNull()
      expect(tooltipBox!.x).toBeGreaterThanOrEqual(0)
      expect(tooltipBox!.x + tooltipBox!.width).toBeLessThanOrEqual(
        viewport.width,
      )
      for (let index = 0; index < 3; index += 1) {
        await toneButtons.nth(index).click()
        await expect(toneButtons.nth(index)).toHaveAttribute(
          'aria-pressed',
          'true',
        )
        await expect(detail.locator('.chord-piano__key[data-active="true"]')).toHaveCount(1)
      }
    }
    if (viewport.width <= 1023) {
      await page.keyboard.press('Escape')
      await expect(detail).toHaveCount(0)
    } else {
      await returnButton.click()
    }
    await expect(chordControl).toBeFocused()
    await expect(chordControl).toHaveAttribute('aria-pressed', 'true')

    if (viewport.width === 1440) {
      await chordControl.click()
      await expect(page.getByText('选择一个组成音')).toBeVisible()
      await expect(
        page.locator('.chord-piano__key[data-active="true"]'),
      ).toHaveCount(0)
      await page.getByRole('button', { name: '返回结构地图' }).click()
    }

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

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: /和弦 C/ }).first().click()
  await expect(page.locator('.chord-orbit__carrier').first()).toHaveCSS(
    'animation-name',
    'none',
  )
  await page.locator('.chord-orbit__note').first().click()
  await expect(page.locator('.tone-education h3')).toBeVisible()
})
