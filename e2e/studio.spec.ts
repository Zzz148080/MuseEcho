import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { fixtureResult, analysisId } from '../frontend/src/test/analysisFixture'
import { ensureChordProgressionFixture, fixturePath } from './support'

const evidence = path.resolve(
  process.env.MUSEECHO_UI_EVIDENCE || 'docs/evidence/frontend-mist-blue',
)
const status = (stage: string, progress: number) => ({
  analysis_id: analysisId,
  stage,
  status: stage,
  progress,
  error_code: stage === 'failed' ? 'audio_decode_failed' : null,
  expires_at: '2099-09-17T00:00:00Z',
  pipeline_version: 'synthetic-ui-test',
  source_kind: 'synthetic_test',
})

async function mockAnalysis(
  page: Page,
  stage = 'complete',
  result = fixtureResult,
  resultDelayMs = 0,
) {
  ensureChordProgressionFixture()
  const source = fs.readFileSync(fixturePath)
  const wav = Buffer.concat([
    source.subarray(0, 44),
    source.subarray(44),
    source.subarray(44),
    source.subarray(44),
  ])
  wav.writeUInt32LE(wav.length - 8, 4)
  wav.writeUInt32LE(wav.length - 44, 40)
  await page.route(`**/api/analyses/${analysisId}/status`, (route) =>
    route.fulfill({ json: status(stage, stage === 'complete' ? 1 : 0.4) }),
  )
  await page.route(`**/api/analyses/${analysisId}`, (route) =>
    resultDelayMs
      ? new Promise<void>((resolve) => setTimeout(resolve, resultDelayMs)).then(
          () => route.fulfill({ json: result }),
        )
      : route.fulfill({ json: result }),
  )
  await page.route(`**/api/analyses/${analysisId}/audio`, (route) => {
    const range = route
      .request()
      .headers()
      .range?.match(/^bytes=(\d+)-(\d*)$/)
    const start = range ? Number(range[1]) : 0
    const end = range?.[2]
      ? Math.min(Number(range[2]), wav.length - 1)
      : wav.length - 1
    return route.fulfill({
      status: range ? 206 : 200,
      contentType: 'audio/wav',
      headers: {
        'Accept-Ranges': 'bytes',
        ...(range
          ? { 'Content-Range': `bytes ${start}-${end}/${wav.length}` }
          : {}),
      },
      body: wav.subarray(start, end + 1),
    })
  })
  await page.goto(`/?analysis=${analysisId}`)
}

async function snapshot(page: Page, name: string) {
  fs.mkdirSync(evidence, { recursive: true })
  await page.screenshot({
    path: path.join(evidence, `${name}.png`),
    fullPage: true,
    animations: 'disabled',
  })
}

test('studio renders readable layouts and preserves one player across window changes', async ({
  page,
}) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/')
  await snapshot(page, 'upload-desktop')
  await page.getByLabel('音频文件').setInputFiles({
    name: '我的音乐.wav',
    mimeType: 'audio/wav',
    buffer: Buffer.from('test'),
  })
  await expect(page.getByText('我的音乐.wav', { exact: true })).toBeVisible()
  await snapshot(page, 'upload-selected')
  await page.setViewportSize({ width: 390, height: 844 })
  await snapshot(page, 'upload-mobile')
  await mockAnalysis(page)
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
  const audio = page.locator('audio')
  await expect(audio).toHaveCount(1)
  const mediaHandle = await audio.elementHandle()
  await openMap(page)
  await page.getByRole('slider', { name: '片段开始' }).fill('8')
  for (const viewport of [
    { width: 320, height: 740 },
    { width: 360, height: 800 },
    { width: 390, height: 844 },
    { width: 412, height: 915 },
    { width: 844, height: 390 },
    { width: 768, height: 1024 },
    { width: 800, height: 1280 },
    { width: 1024, height: 768 },
    { width: 1280, height: 800 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    await page.evaluate(() => window.scrollTo(0, 0))
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    expect(
      await mediaHandle?.evaluate(
        (element) => element === document.querySelector('audio'),
      ),
    ).toBe(true)
    await expect(page.getByTestId('selection')).toBeVisible()
    await snapshot(page, `result-${viewport.width}`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.locator('.retention-panel').scrollIntoViewIfNeeded()
  await expect(page.locator('.mini-player')).toBeVisible()
  await page.getByRole('button', { name: '返回播放器' }).click()
  await expect(page.locator('.player-play')).toBeFocused()
  await page.getByRole('button', { name: '后退 5 秒' }).click()
  await page.locator('.player-play').click()
  await expect
    .poll(() =>
      audio.evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0)
  await page.locator('.player-play').click()
  await expect
    .poll(() => audio.evaluate((element: HTMLAudioElement) => element.paused))
    .toBe(true)
  await page.getByRole('button', { name: '前进 5 秒' }).click()
  await expect
    .poll(() =>
      audio.evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThanOrEqual(5)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  expect(
    await page
      .locator('.workspace-view')
      .evaluate((element) => getComputedStyle(element).animationDuration),
  ).toBe('1e-05s')
  expect(errors).toEqual([])
})

test('studio keeps loading, unknown, failed and terminal states honest', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  for (const stage of ['rhythm', 'failed', 'expired', 'deleted']) {
    await mockAnalysis(page, stage)
    await expect(
      page.getByRole('progressbar', { name: '分析进度' }),
    ).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Music DNA' })).toHaveCount(
      0,
    )
    await snapshot(page, `state-${stage}`)
    await page.unrouteAll({ behavior: 'wait' })
  }
  const unknown = structuredClone(fixtureResult)
  unknown.track.bpm = null
  unknown.track.bpm_confidence = 0
  unknown.track.key_confidence = 0
  unknown.chords = []
  await mockAnalysis(page, 'complete', unknown)
  await expect(page.getByText('暂未判定').first()).toBeVisible()
  await expect(page.locator('.timeline__event--chord')).toHaveCount(0)
  await snapshot(page, 'state-unknown')
})

test.describe('touch and recovery', () => {
  test.use({ hasTouch: true, viewport: { width: 412, height: 915 } })

  test('touch alternatives stay reachable and failed media can retry', async ({
    page,
  }) => {
    await mockAnalysis(page)
    await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
    await openMap(page)
    const chord = page.locator('.timeline__chord-list-button').last()
    const hit = await chord.boundingBox()
    expect(hit?.height).toBeGreaterThanOrEqual(44)
    await chord.tap()
    await expect(page.getByRole('dialog', { name: 'G 和弦' })).toBeVisible()
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.getByRole('button', { name: /组成音 B/ }).tap()
    await expect(
      page.getByRole('heading', { name: 'B · 大三度' }),
    ).toBeVisible()
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '24px'
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await snapshot(page, 'touch-large-text')
    await page.getByRole('button', { name: '返回结构地图' }).tap()
    await expect(chord).toBeFocused()

    await page.unrouteAll({ behavior: 'wait' })
    await mockAnalysis(page)
    const failMedia = (route: Route) => route.abort('failed')
    await page.route(`**/api/analyses/${analysisId}/audio`, failMedia)
    await page.reload()
    await expect(
      page.getByRole('button', { name: '重试读取音频' }),
    ).toBeVisible()
    await snapshot(page, 'state-media-error')
    await page.unroute(`**/api/analyses/${analysisId}/audio`, failMedia)
    await page.getByRole('button', { name: '重试读取音频' }).tap()
    await expect(page.getByText('音频已就绪。')).toBeVisible()
    await expect(
      page.getByRole('button', { name: '重试读取音频' }),
    ).toHaveCount(0)
  })
})

test('slow result response keeps a truthful loading state before rendering', async ({
  page,
}) => {
  await mockAnalysis(page, 'complete', fixtureResult, 1500)
  await expect(page.getByText('正在读取已持久化的分析结果…')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Music DNA' })).toBeVisible()
  await expect(page.locator('.workspace-loading')).toHaveCount(0)
})

test('ten minute synthetic map keeps dense events selectable on a narrow screen', async ({
  page,
}) => {
  // Layout/interaction stress fixture only; the short media fixture is not a long-audio benchmark.
  const result = structuredClone(fixtureResult)
  result.track.duration_seconds = 600
  result.sections = Array.from({ length: 20 }, (_, index) => ({
    ...fixtureResult.sections[0],
    id: `10000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    start_seconds: index * 30,
    end_seconds: (index + 1) * 30,
  }))
  result.chords = Array.from({ length: 300 }, (_, index) => ({
    ...fixtureResult.chords[1],
    id: `20000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    start_seconds: index * 2,
    end_seconds: (index + 1) * 2,
  }))
  result.track.summary!.waveform = {
    algorithm: 'synthetic-stress',
    resolution_seconds: 0.125,
    minimums: Array.from({ length: 4800 }, () => -0.5),
    maximums: Array.from({ length: 4800 }, () => 0.5),
  }
  result.time_series[0].resolution_seconds = 1
  result.time_series[0].points = Array.from({ length: 600 }, (_, index) =>
    index % 2 ? 0.4 : 0.6,
  )
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.setViewportSize({ width: 390, height: 844 })
  await mockAnalysis(page, 'complete', result)
  await openMap(page)
  await expect(page.locator('.timeline__chord-list-button')).toHaveCount(300)
  await page.locator('.timeline__chord-list-button').last().click()
  await expect(page.getByRole('heading', { name: 'G 和弦' })).toBeVisible()
  await expect(page.getByTestId('chord-orbit')).toBeVisible()
  await page.getByRole('button', { name: '返回结构地图' }).click()
  await expect(
    page.locator('.timeline__chord-list-button').last(),
  ).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('slider', { name: '片段开始' }).fill('598')
  await expect(page.getByTestId('selection')).toHaveAttribute(
    'data-start',
    '598',
  )
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true)
  await page.getByRole('button', { name: '清除选区' }).click()
  await expect(page.getByTestId('selection')).toHaveCount(0)
  expect(errors).toEqual([])
})

async function openMap(page: Page) {
  await page
    .getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /结构地图/ })
    .click()
  await expect(page.getByRole('slider', { name: '时间轴缩放' })).toBeVisible()
}

test('approved chord galaxy, piano, zoom and detail return survive every breakpoint', async ({
  page,
}) => {
  await mockAnalysis(page)
  const audio = await page.locator('audio').elementHandle()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await openMap(page)
  for (const width of [320, 390, 599, 600, 768, 1023, 1024, 1440]) {
    await page.setViewportSize({ width, height: width < 600 ? 844 : 1024 })
    await page.getByRole('slider', { name: '时间轴缩放' }).fill('2')
    const content = page.getByTestId('timeline-content')
    const viewport = page.getByTestId('timeline-viewport')
    await expect
      .poll(
        async () =>
          (await content.boundingBox())!.width /
          (await viewport.boundingBox())!.width,
      )
      .toBeCloseTo(2, 1)
    for (const layer of [
      'waveform',
      'sections',
      'chords',
      'energy',
      'events',
    ]) {
      expect(
        (await page.locator(`[data-timeline-layer="${layer}"]`).boundingBox())!
          .width,
      ).toBeCloseTo((await content.boundingBox())!.width, 0)
    }
    const trigger =
      width < 600
        ? page.locator('.timeline__chord-list-button').last()
        : page.locator('button.timeline__event--chord').last()
    await trigger.click()
    const detail = page.locator('.workspace-detail')
    await expect(detail).toBeVisible()
    if (width < 1024) {
      await expect(page.getByRole('dialog', { name: 'G 和弦' })).toBeVisible()
      await expect(page.locator('.app-shell')).toHaveAttribute('inert', '')
    }
    await expect(page.getByText('选择一个组成音')).toBeVisible()
    await expect(page.locator('.chord-orbit__note')).toHaveCount(3)
    await expect(page.locator('.chord-piano')).toBeVisible()
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    expect(
      await page
        .locator('.chord-orbit__carrier')
        .first()
        .evaluate((el) => getComputedStyle(el).animationName),
    ).toBe('chord-orbit-turn')
    await page.getByRole('button', { name: /组成音 G/ }).focus()
    await expect(page.getByTestId('chord-orbit')).toHaveAttribute(
      'data-paused',
      'true',
    )
    await expect(page.getByRole('tooltip')).toBeVisible()
    for (const [pitch, title] of [
      ['G', '根音'],
      ['B', '大三度'],
      ['D', '纯五度'],
    ]) {
      await page
        .getByRole('button', { name: new RegExp(`组成音 ${pitch}`) })
        .press('Enter')
      await expect(
        page.getByRole('heading', { name: `${pitch} · ${title}` }),
      ).toBeVisible()
      await expect(
        page.locator('.chord-piano__key[data-active="true"]'),
      ).toHaveCount(1)
    }
    await page.emulateMedia({ reducedMotion: 'reduce' })
    expect(
      await page
        .locator('.chord-orbit__carrier')
        .first()
        .evaluate((el) => getComputedStyle(el).animationName),
    ).toBe('none')
    await page.getByRole('button', { name: '返回结构地图' }).focus()
    await detail.evaluate((el) => {
      el.scrollTop = 0
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await detail.screenshot({
      path: path.join(evidence, `galaxy-${width}.png`),
      animations: 'disabled',
    })
    const overflow = await detail.evaluate((el) => ({
      width: el.clientWidth,
      scroll: el.scrollWidth,
      nodes: [...el.querySelectorAll('*')]
        .map((n) => ({
          tag: n.className,
          width: n.getBoundingClientRect().width,
          right: n.getBoundingClientRect().right,
        }))
        .filter((n) => n.right > el.getBoundingClientRect().right),
    }))
    expect(overflow, JSON.stringify(overflow)).toMatchObject({
      scroll: overflow.width,
    })
    await page.getByRole('button', { name: '返回结构地图' }).click()
    await expect(trigger).toBeFocused()
    await expect(page.locator('.app-shell')).not.toHaveAttribute('inert', '')
    expect(
      await audio?.evaluate((el) => el === document.querySelector('audio')),
    ).toBe(true)
    await expect(page.locator('audio')).toHaveCount(1)
    await trigger.click()
    await expect(page.getByText('选择一个组成音')).toBeVisible()
    await expect(
      page.locator('.chord-piano__key[data-active="true"]'),
    ).toHaveCount(0)
    await page.getByRole('button', { name: '返回结构地图' }).click()
    await page.getByRole('slider', { name: '时间轴缩放' }).fill('1')
  }
  expect(errors).toEqual([])
})

test('enharmonic notation and voiced piano stay consistent across labels and registers', async ({
  page,
}) => {
  // Synthetic regression fixture reproducing the user's A# / C## / E# screenshot.
  const result = structuredClone(fixtureResult)
  result.chords[1].symbol = 'A#'
  result.chords[1].theory = {
    ...result.chords[1].theory!,
    symbol: 'A#',
    pitch_classes: ['A#', 'C##', 'E#'],
    is_diatonic: false,
    enharmonic_candidates: [],
    limitations: [],
  }
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => {
    const original = AudioContext.prototype.createOscillator
    const frequencies: number[] = []
    ;(
      window as unknown as { auditionFrequencies: number[] }
    ).auditionFrequencies = frequencies
    AudioContext.prototype.createOscillator = function () {
      const oscillator = original.call(this)
      const schedule = oscillator.frequency.setValueAtTime.bind(
        oscillator.frequency,
      )
      oscillator.frequency.setValueAtTime = (value: number, when: number) => {
        frequencies.push(value)
        return schedule(value, when)
      }
      return oscillator
    }
  })
  await page.setViewportSize({ width: 1440, height: 1100 })
  await mockAnalysis(page, 'complete', result)
  await page
    .getByRole('navigation', { name: '分析功能' })
    .getByRole('button', { name: /结构地图/ })
    .click()
  const event = page.getByRole('button', { name: /和弦 B♭，/ }).first()
  await expect(event).toBeVisible()
  await event.click()
  await expect(page.getByRole('heading', { name: 'B♭ 和弦' })).toBeVisible()
  await expect(page.locator('.player-context')).toContainText('B♭')
  await expect(page.locator('.galaxy-caption')).toContainText('B♭ · D · F')
  const piano = page.locator('.piano-lab')
  const third = piano.getByRole('button', { name: '试听 D5' })
  await third.click()
  await expect(
    page.getByRole('button', { name: '组成音 D，大三度' }),
  ).toHaveAttribute('aria-pressed', 'true')
  await expect(third).toHaveAttribute('data-midi', '74')
  const frequency = await page.evaluate(() =>
    (
      window as unknown as { auditionFrequencies: number[] }
    ).auditionFrequencies.at(-1),
  )
  expect(frequency).toBeCloseTo(587.3295, 2)
  const allKeys = piano.locator('.chord-piano__key')
  await expect(piano.locator('button.chord-piano__key')).toHaveCount(
    await allKeys.count(),
  )
  for (const key of await allKeys.all()) {
    const midi = Number(await key.getAttribute('data-midi'))
    await key.click()
    const played = await page.evaluate(() =>
      (
        window as unknown as { auditionFrequencies: number[] }
      ).auditionFrequencies.at(-1),
    )
    expect(played).toBeCloseTo(440 * 2 ** ((midi - 69) / 12), 2)
    await expect(key).toHaveAttribute('data-active', 'true')
    if ((await key.getAttribute('data-chord-tone')) === 'false') {
      expect(
        await key.evaluate((el) =>
          (el as HTMLElement).style.getPropertyValue('--tone-accent'),
        ),
      ).toBe('')
      await expect(
        page.locator('.chord-orbit__note[aria-pressed="true"]'),
      ).toHaveCount(0)
    }
  }
  await expect(piano.locator('[data-chord-tone="true"]')).toHaveCount(3)
  await third.click()
  const white = await third.boundingBox()
  const black = await piano
    .getByRole('button', { name: '试听 B♭4' })
    .boundingBox()
  expect(white!.height / white!.width).toBeGreaterThan(3.8)
  expect(white!.height / white!.width).toBeLessThan(4.5)
  expect(black!.width / white!.width).toBeCloseTo(0.62, 1)
  await page.getByLabel('琴键标注').selectOption('solfege')
  await expect(third).toHaveText('Re5')
  await expect(piano.getByRole('button', { name: '试听 B♭4' })).toHaveText(
    'Si♭4',
  )
  await page.getByLabel('琴键标注').selectOption('none')
  await expect(piano.locator('.piano-key-label')).toHaveCount(0)
  await expect(piano.locator('.piano-chord-marker')).toHaveCount(3)
  for (const marker of await piano.locator('.piano-chord-marker').all()) {
    await expect(marker).toBeVisible()
  }
  await third.focus()
  await page.keyboard.press('Enter')
  await expect(third).toHaveAttribute('aria-pressed', 'true')
  await page.getByLabel('琴键标注').selectOption('pitch')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await piano.screenshot({
    path: path.join(evidence, 'piano-bflat-desktop.png'),
  })
  for (const width of [768, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    await piano.getByRole('button', { name: '低音区' }).click()
    await piano.getByRole('button', { name: '高音区' }).click()
    await expect(piano.locator('[data-chord-tone="true"]')).toHaveCount(3)
    const viewport = piano.getByRole('region', { name: '钢琴音区，可横向滚动' })
    expect(
      await viewport.evaluate((el) => el.scrollWidth > el.clientWidth),
    ).toBe(true)
    await page.getByRole('button', { name: '组成音 F，纯五度' }).click()
    const fifth = piano.getByRole('button', { name: '试听 F5' })
    await expect(fifth).toHaveAttribute('data-active', 'true')
    await fifth.click()
    const neighbour = piano.getByRole('button', { name: '试听 D♭5' })
    await neighbour.click()
    await expect(neighbour).toHaveAttribute('data-active', 'true')
    await expect(neighbour).toHaveAttribute('data-chord-tone', 'false')
    const lowerThird = piano.getByRole('button', { name: '试听 D4' })
    await lowerThird.click()
    const lowerFrequency = await page.evaluate(() =>
      (
        window as unknown as { auditionFrequencies: number[] }
      ).auditionFrequencies.at(-1),
    )
    expect(lowerFrequency).toBeCloseTo(293.6648, 2)
    await expect(lowerThird).toHaveAttribute('data-chord-tone', 'false')
    await piano.getByRole('button', { name: '试听 B♭4' }).click()
    await expect(piano.locator('.chord-piano__key--black .piano-chord-marker')).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true)
    const detail = page.locator('.workspace-detail')
    expect(
      await detail.evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true)
    await piano.screenshot({
      path: path.join(evidence, `piano-bflat-${width}.png`),
    })
    await piano.getByRole('button', { name: '低音区' }).click()
    await piano.getByRole('button', { name: '高音区' }).click()
  }
  expect(errors).toEqual([])
})
