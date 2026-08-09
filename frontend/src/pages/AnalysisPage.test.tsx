// @ts-expect-error Vitest runs in Node; the browser bundle intentionally omits Node types.
import { readFileSync } from 'node:fs'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Button } from '../components/Button'
import { ConfidenceBadge } from '../components/ConfidenceBadge'
import { ErrorNotice } from '../components/ErrorNotice'
import { Panel } from '../components/Panel'
import { AnalysisPage } from './AnalysisPage'

describe('AnalysisPage', () => {
  it('provides a single labelled analysis workspace', () => {
    render(<AnalysisPage />)

    expect(
      screen.getByRole('main', { name: /museecho 音乐解析工作区/i }),
    ).toBeVisible()
  })

  it('describes the honest empty workflow without inventing analysis facts', () => {
    render(<AnalysisPage />)

    expect(screen.getByRole('heading', { name: '开始解析' })).toBeVisible()
    expect(screen.getByRole('region', { name: '分析流程' })).toBeVisible()
    expect(screen.getByText(/尚未选择音频/)).toBeVisible()
    expect(screen.queryByText(/C major|情绪|乐器/i)).not.toBeInTheDocument()
  })
})

describe('accessible foundation components', () => {
  it.each([
    ['high', '高置信'],
    ['medium', '中置信'],
    ['unknown', '证据不足'],
  ] as const)('labels %s confidence in text', (level, label) => {
    render(<ConfidenceBadge level={level} />)

    expect(screen.getByText(label)).toHaveAttribute('data-confidence', level)
  })

  it('announces a recoverable error and its next action', () => {
    render(
      <ErrorNotice
        title="无法读取音频"
        action="请检查文件格式后重新选择。"
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      '无法读取音频请检查文件格式后重新选择。',
    )
  })

  it('uses safe button defaults and unique labels for reusable panels', () => {
    render(
      <>
        <Button variant="secondary">检查</Button>
        <Panel title="证据"><p>第一组</p></Panel>
        <Panel title="证据"><p>第二组</p></Panel>
      </>,
    )

    expect(screen.getByRole('button', { name: '检查' })).toHaveAttribute(
      'type',
      'button',
    )
    const panels = screen.getAllByRole('region', { name: '证据' })
    expect(panels[0].getAttribute('aria-labelledby')).not.toBe(
      panels[1].getAttribute('aria-labelledby'),
    )
  })

  it('keeps focus visible and disables non-essential motion when requested', () => {
    const globalCss = readFileSync('src/styles/global.css', 'utf8')

    expect(globalCss).toMatch(/:focus-visible/)
    expect(globalCss).toMatch(/prefers-reduced-motion:\s*reduce/)
  })

  it('keeps text and action colors at WCAG AA contrast', () => {
    const tokensCss = readFileSync('src/styles/tokens.css', 'utf8')
    const token = (name: string) => {
      const value = tokensCss.match(
        new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'),
      )?.[1]
      expect(value, `missing --${name} color token`).toBeDefined()
      return value as string
    }
    const luminance = (hex: string) => {
      const channels = [1, 3, 5].map((offset) =>
        Number.parseInt(hex.slice(offset, offset + 2), 16) / 255,
      )
      const [red, green, blue] = channels.map((channel) =>
        channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4,
      )
      return 0.2126 * red + 0.7152 * green + 0.0722 * blue
    }
    const contrast = (foreground: string, background: string) => {
      const values = [luminance(foreground), luminance(background)].sort(
        (left, right) => right - left,
      )
      return (values[0] + 0.05) / (values[1] + 0.05)
    }

    expect(contrast(token('fg'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('fg-2'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('muted'), token('bg'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(token('surface'), token('accent'))).toBeGreaterThanOrEqual(
      4.5,
    )
    expect(contrast(token('surface'), token('danger'))).toBeGreaterThanOrEqual(
      4.5,
    )
  })
})
