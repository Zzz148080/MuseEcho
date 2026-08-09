import { expect, test } from '@playwright/test'
import { uploadAndWait } from './support'

test('desktop, tablet, and mobile layouts stay readable and keyboard operable', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await uploadAndWait(page)

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

    const question = await page.locator('.question-panel').boundingBox()
    const retention = await page.locator('.retention-panel').boundingBox()
    expect(question).not.toBeNull()
    expect(retention).not.toBeNull()
    if (!question || !retention) continue
    if (viewport.stacked) {
      expect(retention.y).toBeGreaterThan(question.y + question.height - 2)
      expect(Math.abs(retention.x - question.x)).toBeLessThanOrEqual(2)
    } else {
      expect(Math.abs(retention.y - question.y)).toBeLessThanOrEqual(2)
      expect(retention.x).toBeGreaterThan(question.x + question.width - 2)
    }
  }

  const start = page.getByRole('slider', { name: '片段开始' })
  await start.scrollIntoViewIfNeeded()
  await start.focus()
  await start.press('ArrowRight')
  await expect(page.getByTestId('selection')).toBeVisible()
  await expect(page.getByRole('button', { name: '清除选区' })).toBeEnabled()
  await expect(page.getByRole('button', { name: /和弦 C/ }).first()).toBeVisible()
})
