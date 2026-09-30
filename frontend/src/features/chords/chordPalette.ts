import type { CSSProperties } from 'react'

export interface ChordVisualTheme {
  accent: string
  family: string
}

const ROOT_INDEX: Readonly<Record<string, number>> = {
  C: 0,
  D: 2,
  E: 4,
  F: 5,
  G: 7,
  A: 9,
  B: 11,
}

const ROOT_THEMES: ReadonlyArray<ChordVisualTheme> = [
  { family: 'clay', accent: '#986b5f' },
  { family: 'rose', accent: '#916979' },
  { family: 'plum', accent: '#7d6d87' },
  { family: 'lavender', accent: '#6e728e' },
  { family: 'slate', accent: '#60788b' },
  { family: 'teal', accent: '#557d78' },
  { family: 'sage', accent: '#5f8069' },
  { family: 'olive', accent: '#72805e' },
  { family: 'ochre', accent: '#897953' },
  { family: 'umber', accent: '#8c6d56' },
  { family: 'mauve', accent: '#8b6871' },
  { family: 'brick', accent: '#95675f' },
]

const FALLBACK_THEME: ChordVisualTheme = {
  family: 'neutral',
  accent: '#8f6658',
}

export function chordVisualTheme(symbol: string): ChordVisualTheme {
  const match = /^\s*([A-Ga-g])([#b]?)/.exec(symbol)
  if (!match) return FALLBACK_THEME
  const base = ROOT_INDEX[match[1].toUpperCase()]
  const accidental = match[2] === '#' ? 1 : match[2] === 'b' ? -1 : 0
  return ROOT_THEMES[(base + accidental + 12) % 12]
}

export function chordVisualStyle(symbol: string): CSSProperties {
  return {
    '--chord-accent': chordVisualTheme(symbol).accent,
  } as CSSProperties
}

// Stable pitch colors keep orbit, piano and explanation linked across chords.
const TONE_THEMES = [
  { accent: '#5276b5', soft: '#eaf0fb', ink: '#365783' },
  { accent: '#5786ac', soft: '#eaf2f8', ink: '#385f80' },
  { accent: '#44868f', soft: '#e8f3f4', ink: '#2f6770' },
  { accent: '#7675b7', soft: '#efedf9', ink: '#57558c' },
  { accent: '#8963ab', soft: '#f1ebf8', ink: '#69458a' },
  { accent: '#4e80a3', soft: '#eaf2f8', ink: '#365e7d' },
  { accent: '#9a6da1', soft: '#f5edf6', ink: '#764e7d' },
  { accent: '#666cb2', soft: '#edecfa', ink: '#494f8b' },
  { accent: '#8978b0', soft: '#f1eef8', ink: '#66558d' },
  { accent: '#508d92', soft: '#eaf4f4', ink: '#346a70' },
  { accent: '#9374a5', soft: '#f3edf7', ink: '#715481' },
  { accent: '#a56896', soft: '#f7edf4', ink: '#814c73' },
] as const

export function toneVisualStyle(pitch: string): CSSProperties {
  const match = /^([A-G])([#b]{0,2})$/.exec(pitch)
  const index = match
    ? (ROOT_INDEX[match[1]] +
        [...match[2]].reduce((sum, mark) => sum + (mark === '#' ? 1 : -1), 0) +
        24) %
      12
    : 0
  const theme = TONE_THEMES[index]
  return {
    '--tone-accent': theme.accent,
    '--tone-soft': theme.soft,
    '--tone-ink': theme.ink,
  } as CSSProperties
}
