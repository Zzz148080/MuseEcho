import { chordNotation } from '../chords/musicNotation'
import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../components/Icon'
import type { TimelineController } from '../timeline/useTimeline'
import { formatTime } from '../timeline/Timeline'
import { sectionDisplayLabel } from '../timeline/Timeline'
import type { ChordResult, SectionResult } from '../../api/types'

export interface AudioPlayerProps {
  analysisId: string
  timeline: TimelineController
  currentSection?: SectionResult | null
  currentChord?: ChordResult | null
  onLocateSection?: () => void
  onExploreChord?: (trigger: HTMLButtonElement) => void
}

export function AudioPlayer({
  analysisId,
  timeline,
  currentSection,
  currentChord,
  onLocateSection,
  onExploreChord,
}: AudioPlayerProps) {
  const [playbackStatus, setPlaybackStatus] = useState('点击播放，开始聆听。')
  const [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const [failed, setFailed] = useState(false)
  const [inView, setInView] = useState(true)
  const section = useRef<HTMLElement>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    const media = timeline.mediaRef.current
    const sync = () => {
      if (!media) return
      setPlaying(!media.paused && !media.ended)
      setMuted(media.muted)
      setVolume(media.volume)
      timeline.syncFromMedia()
    }
    document.addEventListener('visibilitychange', sync)
    window.addEventListener('pageshow', sync)
    const observer =
      typeof IntersectionObserver === 'undefined'
        ? null
        : new IntersectionObserver(
            ([entry]) => setInView(entry.isIntersecting),
            { threshold: 0 },
          )
    if (section.current) observer?.observe(section.current)
    return () => {
      alive.current = false
      observer?.disconnect()
      document.removeEventListener('visibilitychange', sync)
      window.removeEventListener('pageshow', sync)
      if (media && !media.paused) media.pause()
    }
  }, [timeline.mediaRef, timeline.syncFromMedia])

  const togglePlayback = async () => {
    const media = timeline.mediaRef.current
    if (!media) return
    if (!media.paused) {
      media.pause()
      return
    }
    try {
      await media.play()
    } catch {
      if (alive.current) {
        setPlaying(false)
        setPlaybackStatus('播放未能开始，请重试或展开原生播放控件。')
      }
    }
  }
  const playButton = (compact = false) => (
    <button
      className={compact ? 'mini-player__play' : 'player-play'}
      type="button"
      aria-label={playing ? '暂停音频' : '播放音频'}
      onClick={() => void togglePlayback()}
    >
      <Icon name={playing ? 'pause' : 'play'} />
    </button>
  )
  return (
    <section
      className="audio-player"
      aria-labelledby="player-title"
      ref={section}
      data-playing={playing}
    >
      <div className="audio-player__heading">
        <div>
          <p className="eyebrow">聆听与探索</p>
          <h2 id="player-title">播放器</h2>
        </div>
        <span className="player-symbol">
          <Icon name="music" />
        </span>
      </div>
      <div className="player-controls">
        <div className="player-transport">
          <button
            className="icon-button"
            type="button"
            aria-label="后退 5 秒"
            onClick={() => timeline.seek(timeline.currentTime - 5)}
          >
            <Icon name="back" />
            <span>5s</span>
          </button>
          {playButton()}
          <button
            className="icon-button"
            type="button"
            aria-label="前进 5 秒"
            onClick={() => timeline.seek(timeline.currentTime + 5)}
          >
            <Icon name="forward" />
            <span>5s</span>
          </button>
        </div>
        <div className="player-scrub">
          <label className="player-progress">
            <span className="sr-only">音频播放进度</span>
            <input
              type="range"
              min={0}
              max={timeline.duration}
              step={0.01}
              value={timeline.currentTime}
              aria-valuetext={`${formatTime(timeline.currentTime)}，共 ${formatTime(timeline.duration)}`}
              onChange={(event) =>
                timeline.seek(event.currentTarget.valueAsNumber)
              }
            />
          </label>
          <div className="player-time">
            <output aria-label="当前播放时间">
              {formatTime(timeline.currentTime)}
            </output>
            <span>{formatTime(timeline.duration)}</span>
          </div>
        </div>
        <div className="player-volume">
          <button
            className="icon-button"
            type="button"
            aria-label={muted ? '取消静音' : '静音'}
            onClick={() => {
              const media = timeline.mediaRef.current
              if (media) media.muted = !media.muted
            }}
          >
            <Icon name={muted || volume === 0 ? 'muted' : 'volume'} />
          </button>
          <label>
            <span className="sr-only">音量</span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(event) => {
                const media = timeline.mediaRef.current
                if (media) {
                  media.volume = event.currentTarget.valueAsNumber
                  media.muted = false
                }
              }}
            />
          </label>
        </div>
      </div>
      {(currentSection || currentChord) && (
        <div className="player-context" aria-label="当前播放线索">
          <span>正在经过</span>
          {currentSection && (
            <button
              type="button"
              onClick={onLocateSection}
              aria-label="定位当前段落"
            >
              <span
                className="context-dot context-dot--section"
                aria-hidden="true"
              />
              {sectionDisplayLabel(currentSection.label)}
            </button>
          )}
          {currentChord && (
            <button
              type="button"
              onClick={(event) => onExploreChord?.(event.currentTarget)}
              aria-label="探索当前和弦"
            >
              <span
                className="context-dot context-dot--chord"
                aria-hidden="true"
              />
              <strong>{chordNotation(currentChord).symbol}</strong> 和弦{' '}
              <span aria-hidden="true">↗</span>
            </button>
          )}
        </div>
      )}
      <div className="player-feedback">
        <p className="audio-player__status" role="status">
          {playbackStatus}
        </p>
        {failed && (
          <button
            className="button button--secondary"
            type="button"
            onClick={() => {
              timeline.mediaRef.current?.load()
              setFailed(false)
              setPlaybackStatus('正在重新读取音频…')
            }}
          >
            重试读取音频
          </button>
        )}
        <p className="audio-player__hint">
          音频按需解密，首次播放或跳转可能需要几秒。
        </p>
      </div>
      <details className="player-native">
        <summary>播放说明与原生控件</summary>
        <p className="audio-player__hint">
          不支持当前音频编码时，请尝试兼容格式重新分析。
        </p>
        <audio
          controls
          preload="metadata"
          ref={timeline.mediaRef}
          src={`/api/analyses/${analysisId}/audio`}
          onCanPlay={() => {
            setFailed(false)
            setPlaybackStatus('音频已就绪。')
          }}
          onPlay={() => setPlaying(true)}
          onPlaying={() => {
            setPlaying(true)
            setPlaybackStatus('正在播放。')
          }}
          onPause={() => {
            setPlaying(false)
            setPlaybackStatus('已暂停。')
          }}
          onEnded={() => {
            setPlaying(false)
            timeline.syncFromMedia()
            setPlaybackStatus('播放结束。')
          }}
          onError={() => {
            setPlaying(false)
            setFailed(true)
            setPlaybackStatus(
              '音频读取失败，可能是网络或浏览器格式支持问题。请重试。',
            )
          }}
          onSeeked={() => {
            timeline.syncFromMedia()
            setPlaybackStatus(
              timeline.mediaRef.current?.paused ? '音频已就绪。' : '正在播放。',
            )
          }}
          onSeeking={() => setPlaybackStatus('正在读取所选位置…')}
          onStalled={() => setPlaybackStatus('音频读取较慢，正在继续加载…')}
          onWaiting={() => setPlaybackStatus('正在按需解密并加载音频…')}
          onVolumeChange={(event) => {
            setVolume(event.currentTarget.volume)
            setMuted(event.currentTarget.muted)
          }}
          onTimeUpdate={timeline.syncFromMedia}
        >
          您的浏览器不支持 HTML 音频播放。
        </audio>
      </details>
      {!inView && (
        <div className="mini-player" aria-label="紧凑播放控制">
          <Icon name="music" />
          <div>
            <strong>{playing ? '正在聆听' : '继续聆听'}</strong>
            <span>
              {formatTime(timeline.currentTime)} /{' '}
              {formatTime(timeline.duration)}
            </span>
          </div>
          <button
            className="icon-button"
            type="button"
            aria-label="返回播放器"
            onClick={() => {
              section.current?.scrollIntoView({ block: 'center' })
              section.current
                ?.querySelector<HTMLButtonElement>('.player-play')
                ?.focus({ preventScroll: true })
            }}
          >
            展开
          </button>
          {playButton(true)}
        </div>
      )}
    </section>
  )
}
