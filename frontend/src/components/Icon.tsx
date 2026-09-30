import type { CSSProperties } from 'react'

const paths = {
  play: 'm9 5 11 7-11 7Z',
  pause: 'M8 5v14M16 5v14',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5',
  music: 'M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4',
  volume: 'M11 4 6 8H3v8h3l5 4ZM16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14',
  muted: 'M11 4 6 8H3v8h3l5 4Zm5 5 5 6m0-6-5 6',
  back: 'M12 8 7 12l5 4M7 12h10M3 5v14',
  forward: 'm12 8 5 4-5 4m5-4H7m14-7v14',
  check: 'm5 12 4 4L19 6',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8c.8-3.2 3.1-5 7-5s6.2 1.8 7 5',
  library: 'M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2Zm0 12h12a2 2 0 0 1 2 2M9 8h6M9 11h5',
  sparkle: 'm12 3 1.3 4.2L17 9l-3.7 1.8L12 15l-1.3-4.2L7 9l3.7-1.8Zm6 11 .7 2.3L21 17l-2.3.7L18 20l-.7-2.3L15 17l2.3-.7ZM5 13l.8 2.2L8 16l-2.2.8L5 19l-.8-2.2L2 16l2.2-.8Z',
  database: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  close: 'M6 6l12 12M18 6 6 18',
  chevron: 'm9 6 6 6-6 6',
  search: 'm20 20-4.3-4.3M18 11a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z',
  panel: 'M4 4h16v16H4zM15 4v16M8 9h3M8 13h3',
  more: 'M6 12h.01M12 12h.01M18 12h.01',
} as const

export function Icon({
  name,
  style,
}: {
  name: keyof typeof paths
  style?: CSSProperties
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
    >
      <path d={paths[name]} />
    </svg>
  )
}
