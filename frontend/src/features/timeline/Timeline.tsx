import { useRef, type CSSProperties, type PointerEvent } from 'react'
import type { AnalysisResult, ChordResult } from '../../api/types'
import { Button } from '../../components/Button'
import { confidenceLevel, isUsableConfidence } from '../confidence'
import type { TimelineController } from './useTimeline'
import { timeToPercent } from './useTimeline'

export interface TimelineProps {
  result: AnalysisResult
  timeline: TimelineController
  onChordSelect?: (chord: ChordResult) => void
}

export function Timeline({ result, timeline, onChordSelect }: TimelineProps) {
  const dragStart = useRef<number | null>(null)
  const summary = result.track.summary
  const waveform = summary?.waveform
  const energy = result.time_series.find((item) => item.kind === 'energy')
  const usableChords = result.chords.filter(
    (chord) =>
      chord.symbol !== 'unknown' &&
      isUsableConfidence(chord.confidence),
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

  return (
    <section className="timeline" aria-labelledby="timeline-title">
      <div className="timeline__heading">
        <div>
          <p className="eyebrow">共享时间坐标</p>
          <h2 id="timeline-title">结构地图</h2>
        </div>
        <output aria-label="当前时间">{formatTime(timeline.currentTime)}</output>
      </div>

      <div className="timeline__canvas">
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
            style={{ left: `${timeToPercent(timeline.currentTime, timeline.duration)}%` }}
          />
        </div>

        <div className="timeline__track" role="group" aria-label="片段选择轨道">
          <span className="timeline__track-label">选区</span>
          <div
            className="timeline__selection-target"
            data-testid="selection-surface"
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
            onPointerCancel={() => {
              dragStart.current = null
            }}
          >
            选择片段以回听和比较
          </div>
        </div>

        <div className="timeline__track" role="group" aria-label="波形轨道">
          <span className="timeline__track-label">波形</span>
          <svg
            aria-hidden="true"
            className="timeline__graph timeline__graph--waveform"
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            {waveform?.minimums.map((minimum, index) => {
              const maximum = waveform.maximums[index]
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
        </div>

        <div className="timeline__track" role="group" aria-label="段落轨道">
          <span className="timeline__track-label">段落</span>
          <div className="timeline__events">
            {result.sections.map((section) => (
              <button
                aria-label={`选择片段 ${formatTime(section.start_seconds)} 至 ${formatTime(section.end_seconds)}`}
                className="timeline__event timeline__event--section"
                data-testid="section-boundary"
                key={section.id}
                onClick={() => {
                  timeline.seek(section.start_seconds)
                  timeline.select(section.start_seconds, section.end_seconds)
                }}
                style={eventPosition(
                  section.start_seconds,
                  section.end_seconds,
                  timeline.duration,
                )}
                type="button"
              />
            ))}
          </div>
        </div>

        <div className="timeline__track" role="group" aria-label="和弦轨道">
          <span className="timeline__track-label">和弦</span>
          <div className="timeline__events">
            {usableChords.map((chord) => (
              <button
                aria-label={`和弦 ${chord.symbol}，${confidenceLabel(chord.confidence)}`}
                className="timeline__event timeline__event--chord"
                key={chord.id}
                onClick={() => {
                  timeline.seek(chord.start_seconds)
                  onChordSelect?.(chord)
                }}
                style={eventPosition(
                  chord.start_seconds,
                  chord.end_seconds,
                  timeline.duration,
                )}
                type="button"
              >
                {chord.symbol}
              </button>
            ))}
            {!usableChords.length ? (
              <span className="timeline__empty-event">暂无局部和声候选</span>
            ) : null}
          </div>
        </div>

        <div className="timeline__track" role="group" aria-label="能量轨道">
          <span className="timeline__track-label">能量</span>
          <svg
            aria-hidden="true"
            className="timeline__graph timeline__graph--energy"
            preserveAspectRatio="none"
            viewBox="0 0 100 100"
          >
            <polyline points={energyPolyline(energy?.points ?? [])} />
          </svg>
        </div>

        <div className="timeline__track" role="group" aria-label="重要事件轨道">
          <span className="timeline__track-label">事件</span>
          <div className="timeline__events">
            {summary?.energy_changes.filter((event) => isUsableConfidence(event.confidence)).map((event, index) => (
              <button
                aria-label={`能量${event.direction === 'rise' ? '上升' : '下降'} ${formatTime(event.timestamp_seconds)}`}
                className="timeline__marker"
                key={`${event.timestamp_seconds}-${index}`}
                onClick={() => timeline.seek(event.timestamp_seconds)}
                style={{ left: `${timeToPercent(event.timestamp_seconds, timeline.duration)}%` }}
                type="button"
              />
            ))}
          </div>
        </div>
      </div>

      <label className="timeline__seek">
        <span>播放位置</span>
        <input
          aria-label="播放位置"
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

function confidenceLabel(confidence: number): string {
  const labels = { high: '高置信', medium: '中置信', unknown: '证据不足' }
  return labels[confidenceLevel(confidence)]
}

function eventPosition(start: number, end: number, duration: number): CSSProperties {
  return {
    left: `${timeToPercent(start, duration)}%`,
    width: `${timeToPercent(end - start, duration)}%`,
  }
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
