import { chordNotation } from '../chords/musicNotation'
import {
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
} from 'react'
import type {
  AnalysisResult,
  ChordResult,
  EnergyChangeSummary,
  SectionResult,
} from '../../api/types'
import { Button } from '../../components/Button'
import {
  MOBILE_WORKSPACE_QUERY,
  useMediaQuery,
} from '../../hooks/useMediaQuery'
import {
  confidenceLevel,
  isUsableConfidence,
  isVisibleChordCandidate,
} from '../confidence'
import { chordVisualStyle, chordVisualTheme } from '../chords/chordPalette'
import type { TimelineController } from './useTimeline'
import { finiteClamp, timeToPercent } from './useTimeline'
import { usePlaybackPaint } from './usePlaybackPaint'
import {
  TIMELINE_MAX_ZOOM,
  TIMELINE_MIN_ZOOM,
  TIMELINE_ZOOM_STEP,
  useTimelineViewport,
} from './useTimelineViewport'

export interface TimelineProps {
  result: AnalysisResult
  timeline: TimelineController
  selectedChord?: ChordResult | null
  onChordSelect?: (chord: ChordResult, trigger: HTMLButtonElement) => void
  onChordDeselect?: () => void
  offline?: boolean
}

const SECTION_LABELS: Readonly<Record<string, string>> = {
  intro: '前奏',
  verse: '主歌',
  pre_chorus: '预副歌',
  chorus: '副歌',
  bridge: '桥段',
  outro: '尾奏',
}

export function Timeline({
  result,
  timeline,
  selectedChord,
  onChordSelect,
  onChordDeselect,
  offline = false,
}: TimelineProps) {
  const dragStart = useRef<number | null>(null)
  const paintSurface = useRef<HTMLDivElement | null>(null)
  const waveformId = useId()
  usePlaybackPaint(paintSurface, timeline.mediaRef, timeline.duration)
  const [hoveredEventKey, setHoveredEventKey] = useState<string | null>(null)
  const [focusedEventKey, setFocusedEventKey] = useState<string | null>(null)
  const isMobile = useMediaQuery(MOBILE_WORKSPACE_QUERY)
  const viewport = useTimelineViewport({
    currentTime: timeline.currentTime,
    duration: timeline.duration,
  })
  const summary = result.track.summary
  const waveform = summary?.waveform
  const waveformPath = useMemo(
    () =>
      waveform?.minimums
        .map((minimum, index) => {
          const x = ((index + 0.5) / waveform.minimums.length) * 100
          return `M${x},${50 - (waveform.maximums[index] ?? minimum) * 45}V${50 - minimum * 45}`
        })
        .join(' ') ?? '',
    [waveform],
  )
  const energy = result.time_series.find((item) => item.kind === 'energy')
  const energyEvents =
    summary?.energy_changes.filter((event) =>
      isUsableConfidence(event.confidence),
    ) ?? []
  const displaySections = buildDisplaySections(result.sections)
  const usableChords = result.chords
    .filter(isVisibleChordCandidate)
    .slice()
    .sort(
      (left, right) =>
        left.start_seconds - right.start_seconds ||
        left.end_seconds - right.end_seconds ||
        left.id.localeCompare(right.id),
    )
  const selectionStyle = timeline.selection
    ? eventPosition(
        timeline.selection.start,
        timeline.selection.end,
        timeline.duration,
      )
    : undefined

  const pointerSeconds = (event: PointerEvent<HTMLDivElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return clientXToSeconds(
      event.clientX,
      bounds.left,
      bounds.width,
      timeline.duration,
    )
  }

  const selectChord = (chord: ChordResult, trigger: HTMLButtonElement) => {
    timeline.seek(chord.start_seconds)
    onChordSelect?.(chord, trigger)
  }

  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <div className="timeline__heading">
        <div>
          <p className="eyebrow">共享时间坐标</p>
          <h2 id="timeline-title">结构地图</h2>
          <p className="timeline__guide">
            从左到右，沿歌曲时间探索段落与和弦。
          </p>
        </div>
        <output aria-label="当前时间">
          {formatTime(timeline.currentTime)}
        </output>
      </div>

      <div className="timeline__toolbar">
        <div className="timeline__legend" aria-label="地图图例">
          <span>
            <i data-kind="waveform" />
            波形
          </span>
          <span>
            <i data-kind="section" />
            段落
          </span>
          <span>
            <i data-kind="chord" />
            和弦
          </span>
          <span>
            <i data-kind="energy" />
            动态
          </span>
        </div>
        <button
          className="timeline__reset"
          type="button"
          disabled={viewport.disabled || viewport.zoom === 1}
          onClick={() => viewport.setZoom(1)}
        >
          <span aria-hidden="true">↔</span> 全曲视野
        </button>
      </div>
      <label className="timeline__zoom">
        <span>时间轴缩放</span>
        <input
          aria-label="时间轴缩放"
          disabled={viewport.disabled}
          max={TIMELINE_MAX_ZOOM}
          min={TIMELINE_MIN_ZOOM}
          onChange={(event) =>
            viewport.setZoom(event.currentTarget.valueAsNumber)
          }
          step={TIMELINE_ZOOM_STEP}
          type="range"
          value={viewport.zoom}
        />
        <output aria-label="当前缩放倍率">{viewport.zoom.toFixed(2)}×</output>
      </label>

      <div className="timeline__frame">
        <div aria-hidden="true" className="timeline__labels">
          {['选区', '波形', '段落', '和弦', '动态强弱', '事件'].map((label) => (
            <span className="timeline__track-label" key={label}>
              {label}
            </span>
          ))}
        </div>
        <div
          className="timeline__viewport"
          data-testid="timeline-viewport"
          ref={viewport.viewportRef}
        >
          <div
            className="timeline__content"
            ref={paintSurface}
            data-testid="timeline-content"
            style={{
              width:
                viewport.contentWidth > 0
                  ? `${viewport.contentWidth}px`
                  : '100%',
            }}
          >
            <div className="timeline__overlay" aria-hidden="true">
              {selectionStyle ? (
                <div
                  className="timeline__selection"
                  data-end={String(timeline.selection?.end)}
                  data-start={String(timeline.selection?.start)}
                  data-testid="selection"
                  style={selectionStyle}
                />
              ) : null}
              <div
                className="timeline__playhead"
                data-seconds={String(timeline.currentTime)}
                data-testid="playhead"
                data-timeline-layer="playhead"
                style={{
                  left: `var(--playback, ${timeToPercent(timeline.currentTime, timeline.duration)}%)`,
                }}
              />
            </div>

            <div
              aria-label="片段选择轨道"
              className="timeline__track-content"
              data-timeline-layer="selection"
              role="group"
            >
              <div
                className="timeline__selection-target"
                data-testid="selection-surface"
                onPointerCancel={() => {
                  dragStart.current = null
                }}
                onPointerDown={(event) => {
                  if (event.button !== 0) return
                  dragStart.current = pointerSeconds(event)
                  event.currentTarget.setPointerCapture?.(event.pointerId)
                }}
                onPointerMove={(event) => {
                  if (dragStart.current !== null) {
                    timeline.select(dragStart.current, pointerSeconds(event))
                  }
                }}
                onPointerUp={(event) => {
                  if (dragStart.current !== null) {
                    timeline.select(dragStart.current, pointerSeconds(event))
                    dragStart.current = null
                  }
                  if (
                    event.currentTarget.hasPointerCapture?.(event.pointerId)
                  ) {
                    event.currentTarget.releasePointerCapture(event.pointerId)
                  }
                }}
              >
                {offline ? '选择片段以查看和比较结构' : '选择片段以回听和比较'}
              </div>
            </div>

            <div
              aria-label="波形轨道"
              className="timeline__track-content"
              data-timeline-layer="waveform"
              role="group"
            >
              {waveform?.minimums.length ? (
                <svg
                  aria-hidden="true"
                  className="timeline__graph timeline__graph--waveform"
                  preserveAspectRatio="none"
                  viewBox="0 0 100 100"
                >
                  <defs>
                    <clipPath id={`${waveformId}-clip`}>
                      <rect
                        x="0"
                        y="0"
                        height="100"
                        style={{ width: 'var(--playback, 0%)' }}
                      />
                    </clipPath>
                  </defs>
                  <path d={waveformPath} />
                  <path
                    d={waveformPath}
                    className="timeline__waveform-played"
                    clipPath={`url(#${waveformId}-clip)`}
                  />
                </svg>
              ) : (
                <TrackEmpty>暂无波形摘要</TrackEmpty>
              )}
            </div>

            <div
              aria-label="段落轨道"
              className="timeline__track-content"
              data-timeline-layer="sections"
              role="group"
            >
              <div className="timeline__events">
                {displaySections.map((section) => {
                  const label = sectionDisplayLabel(section.label)
                  return (
                    <button
                      aria-label={`${label}，选择片段 ${formatTime(section.start_seconds)} 至 ${formatTime(section.end_seconds)}`}
                      className="timeline__event timeline__event--section"
                      data-testid="section-boundary"
                      key={section.id}
                      onClick={() => {
                        timeline.seek(section.start_seconds)
                        timeline.select(
                          section.start_seconds,
                          section.end_seconds,
                        )
                      }}
                      style={eventPosition(
                        section.start_seconds,
                        section.end_seconds,
                        timeline.duration,
                      )}
                      type="button"
                    >
                      {label}
                    </button>
                  )
                })}
                {!displaySections.length ? (
                  <TrackEmpty>暂无段落信息</TrackEmpty>
                ) : null}
              </div>
            </div>

            <div
              aria-label="和弦轨道"
              className="timeline__track-content"
              data-timeline-layer="chords"
              role="group"
            >
              <div className="timeline__events">
                {usableChords.map((chord) => {
                  const current = isChordCurrent(chord, timeline.currentTime)
                  const chordStyle = {
                    ...eventPosition(
                      chord.start_seconds,
                      chord.end_seconds,
                      timeline.duration,
                    ),
                    ...chordVisualStyle(chord.symbol),
                  }
                  const chordFamily = chordVisualTheme(chord.symbol).family
                  return isMobile ? (
                    <span
                      aria-hidden="true"
                      className="timeline__event timeline__event--chord timeline__event--visual"
                      data-chord-family={chordFamily}
                      data-current={String(current)}
                      key={chord.id}
                      style={chordStyle}
                    >
                      {chordNotation(chord).symbol}
                    </span>
                  ) : (
                    <button
                      aria-current={current ? 'true' : undefined}
                      aria-label={`和弦 ${chordNotation(chord).symbol}，${confidenceLabel(chord.confidence)}${current ? '，正在经过' : ''}`}
                      aria-pressed={selectedChord?.id === chord.id}
                      className="timeline__event timeline__event--chord"
                      data-chord-family={chordFamily}
                      data-current={String(current)}
                      key={chord.id}
                      onClick={(event) =>
                        selectChord(chord, event.currentTarget)
                      }
                      style={chordStyle}
                      type="button"
                    >
                      <span className="timeline__event-symbol">
                        {chordNotation(chord).symbol}
                      </span>
                      {current ? (
                        <span className="timeline__event-hint">
                          正在经过 {chordNotation(chord).symbol} 和弦
                        </span>
                      ) : null}
                    </button>
                  )
                })}
                {!usableChords.length ? (
                  <TrackEmpty>暂无局部和声候选</TrackEmpty>
                ) : null}
              </div>
            </div>

            <div
              aria-label="动态强弱轨道"
              className="timeline__track-content"
              data-timeline-layer="energy"
              role="group"
            >
              {energy?.points.length ? (
                <svg
                  aria-hidden="true"
                  className="timeline__graph timeline__graph--energy"
                  preserveAspectRatio="none"
                  viewBox="0 0 100 100"
                >
                  <polyline points={energyPolyline(energy.points)} />
                </svg>
              ) : (
                <TrackEmpty>暂无动态曲线</TrackEmpty>
              )}
            </div>

            <div
              aria-label="重要事件轨道"
              className="timeline__track-content"
              data-timeline-layer="events"
              role="group"
            >
              <div className="timeline__events">
                {energyEvents.map((event, index) => {
                  const label = energyEventLabel(event)
                  const eventKey = `${event.timestamp_seconds}-${index}`
                  const current = isEventNear(
                    event.timestamp_seconds,
                    timeline.currentTime,
                  )
                  const previewed =
                    hoveredEventKey === eventKey || focusedEventKey === eventKey
                  return (
                    <button
                      aria-current={current ? 'true' : undefined}
                      aria-label={`${label}${current ? '，正在经过' : ''}`}
                      className="timeline__marker"
                      data-current={String(current)}
                      key={eventKey}
                      onClick={() => timeline.seek(event.timestamp_seconds)}
                      onBlur={() => setFocusedEventKey(null)}
                      onFocus={() => setFocusedEventKey(eventKey)}
                      onMouseEnter={() => setHoveredEventKey(eventKey)}
                      onMouseLeave={() => setHoveredEventKey(null)}
                      style={{
                        left: `${timeToPercent(event.timestamp_seconds, timeline.duration)}%`,
                      }}
                      type="button"
                    >
                      <span
                        aria-hidden="true"
                        className="timeline__marker-dot"
                      />
                      {current || previewed ? (
                        <span className="timeline__marker-label">{label}</span>
                      ) : null}
                    </button>
                  )
                })}
                {!energyEvents.length ? (
                  <TrackEmpty>暂无事件</TrackEmpty>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      </div>

      {isMobile && usableChords.length ? (
        <section
          aria-labelledby="timeline-chord-list-title"
          className="timeline__chord-list"
        >
          <h3 id="timeline-chord-list-title">和弦事件列表</h3>
          <ol>
            {usableChords.map((chord) => {
              const current = isChordCurrent(chord, timeline.currentTime)
              return (
                <li key={chord.id}>
                  <button
                    aria-current={current ? 'true' : undefined}
                    aria-label={`和弦 ${chordNotation(chord).symbol}，${formatTime(chord.start_seconds)} 至 ${formatTime(chord.end_seconds)}，${confidenceLabel(chord.confidence)}${current ? '，正在经过' : ''}`}
                    aria-pressed={selectedChord?.id === chord.id}
                    className="timeline__chord-list-button"
                    data-chord-family={chordVisualTheme(chord.symbol).family}
                    onClick={(event) => selectChord(chord, event.currentTarget)}
                    style={chordVisualStyle(chord.symbol)}
                    type="button"
                  >
                    <strong>{chordNotation(chord).symbol}</strong>
                    <span>
                      {formatTime(chord.start_seconds)}–
                      {formatTime(chord.end_seconds)} ·{' '}
                      {confidenceLabel(chord.confidence)}
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        </section>
      ) : null}

      {selectedChord && onChordDeselect ? (
        <Button
          className="timeline__clear-chord"
          onClick={onChordDeselect}
          variant="secondary"
        >
          清除和弦选择
        </Button>
      ) : null}

      <label className="timeline__seek">
        <span>{offline ? '时间位置' : '播放位置'}</span>
        <input
          aria-label={offline ? '时间位置' : '播放位置'}
          disabled={timeline.duration <= 0}
          max={timeline.duration}
          min={0}
          onChange={(event) => timeline.seek(event.currentTarget.valueAsNumber)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
              event.preventDefault()
              timeline.seek(
                timeline.currentTime + (event.key === 'ArrowRight' ? 5 : -5),
              )
            }
          }}
          step={0.01}
          type="range"
          value={timeline.currentTime}
        />
      </label>
      <fieldset className="timeline__selection-controls">
        <legend>片段选择</legend>
        <label>
          <span>片段开始</span>
          <input
            disabled={timeline.duration <= 0}
            max={timeline.duration}
            min={0}
            onChange={(event) =>
              timeline.select(
                event.currentTarget.valueAsNumber,
                timeline.selection?.end ?? timeline.duration,
              )
            }
            step={0.1}
            type="range"
            value={timeline.selection?.start ?? 0}
          />
        </label>
        <label>
          <span>片段结束</span>
          <input
            disabled={timeline.duration <= 0}
            max={timeline.duration}
            min={0}
            onChange={(event) =>
              timeline.select(
                timeline.selection?.start ?? 0,
                event.currentTarget.valueAsNumber,
              )
            }
            step={0.1}
            type="range"
            value={timeline.selection?.end ?? timeline.duration}
          />
        </label>
        <Button
          disabled={!timeline.selection}
          onClick={timeline.clearSelection}
          variant="secondary"
        >
          清除选区
        </Button>
      </fieldset>
      <p
        className="timeline__text-summary"
        aria-live="polite"
        data-selected={Boolean(timeline.selection)}
      >
        当前 {formatTime(timeline.currentTime)}
        {timeline.selection
          ? `；已选 ${formatTime(timeline.selection.start)}–${formatTime(timeline.selection.end)}`
          : offline ? '；选择片段以查看和比较结构' : '；选择片段以回听和比较'}
        {timeline.selection && (
          <span className="timeline__selection-duration">
            时长{' '}
            {(timeline.selection.end - timeline.selection.start).toFixed(1)} 秒
          </span>
        )}
      </p>
    </section>
  )
}

function TrackEmpty({ children }: { children: string }) {
  return <span className="timeline__empty-event">{children}</span>
}

function confidenceLabel(confidence: number): string {
  const labels = {
    high: '高置信',
    medium: '中置信',
    low: '低置信',
    unknown: '证据不足',
  }
  return labels[confidenceLevel(confidence)]
}

function eventPosition(
  start: number,
  end: number,
  duration: number,
): CSSProperties {
  return {
    left: `${timeToPercent(start, duration)}%`,
    width: `${timeToPercent(end - start, duration)}%`,
  }
}

export function sectionDisplayLabel(label: string): string {
  const family = sectionFamily(label)
  if (!family) return '未命名段落'
  if (/^[A-Z]$/.test(family)) return `${family} 段`
  return SECTION_LABELS[family] ?? `段落 ${label.trim()}`
}

export function buildDisplaySections(
  sections: SectionResult[],
): SectionResult[] {
  const ordered = sections
    .filter(
      (section) =>
        Number.isFinite(section.start_seconds) &&
        Number.isFinite(section.end_seconds) &&
        section.end_seconds > section.start_seconds,
    )
    .slice()
    .sort(
      (left, right) =>
        left.start_seconds - right.start_seconds ||
        left.end_seconds - right.end_seconds ||
        left.id.localeCompare(right.id),
    )

  return ordered.reduce<SectionResult[]>((merged, section) => {
    const family = sectionFamily(section.label)
    const normalized = { ...section, label: family || section.label.trim() }
    const previous = merged.at(-1)
    if (
      previous &&
      sectionFamily(previous.label) === family &&
      section.start_seconds <= previous.end_seconds + 0.5
    ) {
      previous.end_seconds = Math.max(previous.end_seconds, section.end_seconds)
      previous.confidence = Math.min(previous.confidence, section.confidence)
      return merged
    }
    merged.push(normalized)
    return merged
  }, [])
}

function sectionFamily(label: string): string {
  const trimmed = label.trim()
  if (!trimmed) return ''
  const normalized = trimmed.toLowerCase().replace(/[\s-]+/g, '_')
  const semantic =
    /^(intro|verse|pre_chorus|chorus|bridge|outro)(?:_?\d+)?$/.exec(normalized)
  if (semantic) return semantic[1]
  const letter = /^([a-z])(?:[\s_-]*\d+)?$/i.exec(trimmed)
  return letter ? letter[1].toUpperCase() : trimmed
}

export function energyEventLabel(event: EnergyChangeSummary): string {
  const direction = event.direction === 'rise' ? '动态上升' : '动态下降'
  const magnitude = Math.round(finiteClamp(event.magnitude, 0, 1) * 100)
  return `${direction} ${formatTime(event.timestamp_seconds)}，强度 ${magnitude}%`
}

export function isChordCurrent(
  chord: ChordResult,
  currentTime: number,
): boolean {
  return currentTime >= chord.start_seconds && currentTime < chord.end_seconds
}

export function isEventNear(
  timestamp: number,
  currentTime: number,
  windowSeconds = 0.75,
): boolean {
  return Math.abs(timestamp - currentTime) <= windowSeconds
}

export function clientXToSeconds(
  clientX: number,
  left: number,
  width: number,
  duration: number,
): number {
  if (!Number.isFinite(width) || width <= 0 || duration <= 0) return 0
  return Math.min(duration, Math.max(0, ((clientX - left) / width) * duration))
}

function energyPolyline(points: number[]): string {
  if (!points.length) return ''
  return points
    .map((point, index) => {
      const x = points.length === 1 ? 0 : (index / (points.length - 1)) * 100
      const y = 100 - Math.min(1, Math.max(0, point)) * 100
      return `${x},${y}`
    })
    .join(' ')
}

export function formatTime(seconds: number): string {
  const safe = Math.max(0, Number.isFinite(seconds) ? seconds : 0)
  const minutes = Math.floor(safe / 60)
  const remainder = Math.floor(safe % 60)
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}
