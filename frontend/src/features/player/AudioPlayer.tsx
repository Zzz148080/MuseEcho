import { useState } from 'react'
import type { TimelineController } from '../timeline/useTimeline'
import { formatTime } from '../timeline/Timeline'

export interface AudioPlayerProps {
  analysisId: string
  timeline: TimelineController
}

export function AudioPlayer({ analysisId, timeline }: AudioPlayerProps) {
  const [playbackStatus, setPlaybackStatus] = useState<string | null>(null)

  return (
    <section className="audio-player" aria-labelledby="player-title">
      <div className="audio-player__heading">
        <div>
          <p className="eyebrow">受权加密音频</p>
          <h2 id="player-title">播放器</h2>
        </div>
        <output aria-label="当前播放时间">
          {formatTime(timeline.currentTime)} / {formatTime(timeline.duration)}
        </output>
      </div>
      <audio
        controls
        onCanPlay={() => setPlaybackStatus('音频已就绪。')}
        onError={() => setPlaybackStatus('音频读取失败，请刷新页面后重试。')}
        onPlaying={() => setPlaybackStatus('正在播放。')}
        onSeeked={() => {
          timeline.syncFromMedia()
          setPlaybackStatus('音频已就绪。')
        }}
        onSeeking={() => setPlaybackStatus('正在读取所选位置…')}
        onStalled={() => setPlaybackStatus('音频读取较慢，正在继续加载…')}
        onTimeUpdate={timeline.syncFromMedia}
        onWaiting={() => setPlaybackStatus('正在按需解密并加载音频…')}
        preload="metadata"
        ref={timeline.mediaRef}
        src={`/api/analyses/${analysisId}/audio`}
      >
        您的浏览器不支持 HTML 音频播放。
      </audio>
      <p className="audio-player__hint">
        音频会按需解密；首次播放或跳转通常需要几秒，大型无损文件可能稍慢。
      </p>
      {playbackStatus ? (
        <p className="audio-player__status" role="status">
          {playbackStatus}
        </p>
      ) : null}
    </section>
  )
}
