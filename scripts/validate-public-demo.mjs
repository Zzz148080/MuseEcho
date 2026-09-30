import fs from 'node:fs'
import path from 'node:path'
import { chromium } from '@playwright/test'

const origin = process.env.MUSEECHO_DEMO_ORIGIN || 'https://museecho.toolgate.cloud'
const audioPath = path.resolve(
  process.env.MUSEECHO_DEMO_AUDIO || 'demo-assets/museecho-demo-progression.wav',
)
const evidenceRoot = path.resolve(
  process.env.MUSEECHO_DEMO_EVIDENCE || 'outputs/submission-evidence',
)

if (!fs.existsSync(audioPath)) {
  throw new Error(`Demo audio is missing: ${audioPath}`)
}
fs.mkdirSync(evidenceRoot, { recursive: true })

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext({
  baseURL: origin,
  viewport: { width: 1440, height: 900 },
})
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})

try {
  const response = await page.goto('/', { waitUntil: 'networkidle', timeout: 30_000 })
  if (!response?.ok()) throw new Error(`Homepage returned ${response?.status() ?? 'no response'}`)
  await page.getByLabel('音频文件').setInputFiles(audioPath)
  await page.getByRole('checkbox', { name: /有权分析/ }).check()
  await page.getByRole('checkbox', { name: /加密保留最长 24 小时/ }).check()
  const uploadResponse = page.waitForResponse(
    (candidate) =>
      candidate.url().endsWith('/api/analyses') &&
      candidate.request().method() === 'POST',
  )
  await page.getByRole('button', { name: /开始分析/ }).click()
  const accepted = await uploadResponse
  if (accepted.status() !== 202) {
    throw new Error(`Upload returned ${accepted.status()}: ${await accepted.text()}`)
  }
  const payload = await accepted.json()
  if (typeof payload.analysis_id !== 'string') throw new Error('Upload returned no analysis id')
  await page.getByText('分析完成').waitFor({ state: 'visible', timeout: 90_000 })
  await page.getByRole('heading', { name: 'Music DNA' }).waitFor({ state: 'visible' })
  await page.screenshot({
    path: path.join(evidenceRoot, '01-web-desktop.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.getByRole('button', { name: /沿时间轴继续/ }).click()
  await page.getByRole('heading', { name: '结构地图' }).waitFor({ state: 'visible' })
  await page.screenshot({
    path: path.join(evidenceRoot, '02-web-map.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /歌曲概览/ })
    .click()
  await page.screenshot({
    path: path.join(evidenceRoot, '03-web-phone.png'),
    fullPage: true,
    animations: 'disabled',
  })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.screenshot({
    path: path.join(evidenceRoot, '04-web-tablet.png'),
    fullPage: true,
    animations: 'disabled',
  })
  if (errors.length > 0) throw new Error(errors.join('\n'))
  process.stdout.write(`Public demo passed: ${payload.analysis_id}\nEvidence: ${evidenceRoot}\n`)
} finally {
  await context.close()
  await browser.close()
}
