import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync('src/styles/tokens.css', 'utf8')

function token(name: string): string {
  const value = css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
  expect(value, `missing --${name}`).toBeDefined()
  return value as string
}

function luminance(hex: string): number {
  const [red, green, blue] = [1, 3, 5]
    .map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255)
    .map((channel) =>
      channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4,
    )
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function contrast(foreground: string, background: string): number {
  const values = [luminance(foreground), luminance(background)].sort(
    (left, right) => right - left,
  )
  return (values[0] + 0.05) / (values[1] + 0.05)
}

describe('Morandi design tokens', () => {
  it('defines the required semantic tokens', () => {
    const names = [
      'bg',
      'surface',
      'surface-soft',
      'fg',
      'fg-2',
      'muted',
      'accent',
      'accent-strong',
      'accent-soft',
      'chord',
      'structure',
      'success',
      'warn',
      'danger',
      'border',
    ]

    for (const name of names) token(name)
    expect(css).toMatch(/--shadow-soft:\s*[^;]+;/)
    expect(css).toMatch(/--safe-bottom:\s*[^;]+;/)
  })

  it.each([
    ['fg', 'bg'],
    ['fg-2', 'bg'],
    ['muted', 'bg'],
    ['accent', 'surface'],
    ['chord', 'surface'],
    ['structure', 'surface'],
    ['surface', 'accent'],
    ['surface', 'danger'],
  ])('keeps --%s readable on --%s', (foreground, background) => {
    expect(contrast(token(foreground), token(background))).toBeGreaterThanOrEqual(4.5)
  })
})
