import { expect, test } from '@playwright/test'
import { selectTimelineSegment, uploadAndWait } from './support'

test('upload to delete completes without console errors', async ({ page }) => {
  const runtimeErrors: string[] = []
  const networkErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') runtimeErrors.push(message.text())
  })
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  page.on('requestfailed', (request) => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
      networkErrors.push(`${request.method()} ${request.url()}`)
    }
  })
  page.on('response', (response) => {
    if (response.status() >= 500) {
      networkErrors.push(`${response.status()} ${response.url()}`)
    }
  })

  await uploadAndWait(page)
  await selectTimelineSegment(page)
  await expect(page.locator('.question-panel')).toHaveCount(0)

  await page.locator('.retention-panel summary').click()
  await page.getByRole('checkbox', { name: /了解删除不可恢复/ }).check()
  await page.getByRole('button', { name: '永久删除分析' }).click()
  await expect(page.getByRole('heading', { name: '分析已永久删除' })).toBeVisible()
  expect(runtimeErrors).toEqual([])
  expect(networkErrors).toEqual([])
})
