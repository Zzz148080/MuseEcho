import type { TimelineController } from '../timeline/useTimeline'
import { formatTime } from '../timeline/Timeline'

export interface AudioPlayerProps {
  analysisId: string
  timeline: TimelineController
}

export function AudioPlayer({ analysisId, timeline }: AudioPlayerProps) {
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
        onSeeked={timeline.syncFromMedia}
        onTimeUpdate={timeline.syncFromMedia}
        preload="metadata"
        ref={timeline.mediaRef}
        src={`/api/analyses/${analysisId}/audio`}
      >
        您的浏览器不支持 HTML 音频播放。
      </audio>
    </section>
  )
}
