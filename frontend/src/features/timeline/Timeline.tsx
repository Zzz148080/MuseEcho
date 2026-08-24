import { useRef, type CSSProperties, type PointerEvent } from 'react'
import type {
  AnalysisResult,
  ChordResult,
  EnergyChangeSummary,
} from '../../api/types'
import { Button } from '../../components/Button'
import { MOBILE_WORKSPACE_QUERY, useMediaQuery } from '../../hooks/useMediaQuery'
import {
  confidenceLevel,
  isUsableConfidence,
  isVisibleChordCandidate,
} from '../confidence'
import type { TimelineController } from './useTimeline'
import { finiteClamp, timeToPercent } from './useTimeline'
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
}: TimelineProps) {
  const dragStart = useRef<number | null>(null)
  const isMobile = useMediaQuery(MOBILE_WORKSPACE_QUERY)
  const viewport = useTimelineViewport({
    currentTime: timeline.currentTime,
    duration: timeline.duration,
  })
  const summary = result.track.summary
  const waveform = summary?.waveform
  const energy = result.time_series.find((item) => item.kind === 'energy')
  const energyEvents =
    summary?.energy_changes.filter((event) =>
      isUsableConfidence(event.confidence),
    ) ?? []
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
        </div>
        <output aria-label="当前时间">{formatTime(timeline.currentTime)}</output>
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
                  left: `${timeToPercent(timeline.currentTime, timeline.duration)}%`,
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
                  if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
                    event.currentTarget.releasePointerCapture(event.pointerId)
                  }
                }}
              >
                选择片段以回听和比较
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
                  {waveform.minimums.map((minimum, index) => {
                    const maximum = waveform.maximums[index] ?? minimum
                    const x = ((index + 0.5) / waveform.minimums.length) * 100
                    return (
                      <line
                        key={index}
                        x1={x}
                        x2={x}
                        y1={50 - maximum * 45}
                        y2={50 - minimum * 45}
                      />
                    )
                  })}
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
                {result.sections.map((section) => {
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
                {!result.sections.length ? (
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
                  return isMobile ? (
                    <span
                      aria-hidden="true"
                      className="timeline__event timeline__event--chord timeline__event--visual"
                      data-current={String(current)}
                      key={chord.id}
                      style={eventPosition(
                        chord.start_seconds,
                        chord.end_seconds,
                        timeline.duration,
                      )}
                    >
                      {chord.symbol}
                    </span>
                  ) : (
                    <button
                      aria-current={current ? 'true' : undefined}
                      aria-label={`和弦 ${chord.symbol}，${confidenceLabel(chord.confidence)}${current ? '，正在经过' : ''}`}
                      aria-pressed={selectedChord?.id === chord.id}
                      className="timeline__event timeline__event--chord"
                      data-current={String(current)}
                      key={chord.id}
                      onClick={(event) => selectChord(chord, event.currentTarget)}
                      style={eventPosition(
                        chord.start_seconds,
                        chord.end_seconds,
                        timeline.duration,
                      )}
                      type="button"
                    >
                      <span className="timeline__event-symbol">{chord.symbol}</span>
                      {current ? (
                        <span className="timeline__event-hint">
                          正在经过 {chord.symbol} 和弦
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
                  const current = isEventNear(
                    event.timestamp_seconds,
                    timeline.currentTime,
                  )
                  return (
                    <button
                      aria-current={current ? 'true' : undefined}
                      aria-label={`${label}${current ? '，正在经过' : ''}`}
                      className="timeline__marker"
                      data-current={String(current)}
                      key={`${event.timestamp_seconds}-${index}`}
                      onClick={() => timeline.seek(event.timestamp_seconds)}
                      style={{
                        left: `${timeToPercent(event.timestamp_seconds, timeline.duration)}%`,
                      }}
                      type="button"
                    >
                      <span aria-hidden="true" className="timeline__marker-dot" />
                      <span className="timeline__marker-label">{label}</span>
                    </button>
                  )
                })}
                {!energyEvents.length ? <TrackEmpty>暂无事件</TrackEmpty> : null}
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
                    aria-label={`和弦 ${chord.symbol}，${formatTime(chord.start_seconds)} 至 ${formatTime(chord.end_seconds)}，${confidenceLabel(chord.confidence)}${current ? '，正在经过' : ''}`}
                    aria-pressed={selectedChord?.id === chord.id}
                    className="timeline__chord-list-button"
                    onClick={(event) => selectChord(chord, event.currentTarget)}
                    type="button"
                  >
                    <strong>{chord.symbol}</strong>
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
        <span>播放位置</span>
        <input
          aria-label="播放位置"
          disabled={timeline.duration <= 0}
          max={timeline.duration}
          min={0}
          onChange={(event) => timeline.seek(event.currentTarget.valueAsNumber)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
              event.preventDefault()
              timeline.seek(
                timeline.currentTime +
                  (event.key === 'ArrowRight' ? 5 : -5),
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
      <p className="timeline__text-summary" aria-live="polite">
        当前 {formatTime(timeline.currentTime)}
        {timeline.selection
          ? `；已选 ${formatTime(timeline.selection.start)}–${formatTime(timeline.selection.end)}`
          : '；选择片段以回听和比较'}
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
  const trimmed = label.trim()
  if (!trimmed) return '未命名段落'
  return SECTION_LABELS[trimmed.toLowerCase()] ?? `段落 ${trimmed}`
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
  return (
    currentTime >= chord.start_seconds && currentTime < chord.end_seconds
  )
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
  return Math.min(
    duration,
    Math.max(0, ((clientX - left) / width) * duration),
  )
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
