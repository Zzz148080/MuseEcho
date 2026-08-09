import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { analysisId } from '../../test/analysisFixture'
import { AudioPlayer } from './AudioPlayer'
import { useTimeline } from '../timeline/useTimeline'

function Harness() {
  const timeline = useTimeline(12)
  return <AudioPlayer analysisId={analysisId} timeline={timeline} />
}

describe('AudioPlayer', () => {
  it('uses the authorized Range endpoint and synchronizes media time', () => {
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')

    expect(media).toHaveAttribute('src', `/api/analyses/${analysisId}/audio`)
    if (!media) throw new Error('missing audio element')
    media.currentTime = 4.25
    fireEvent.timeUpdate(media)

    expect(screen.getByLabelText(/当前播放时间/)).toHaveTextContent('0:04')
  })
})
