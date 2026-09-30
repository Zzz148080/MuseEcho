import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { analysisId } from '../../test/analysisFixture'
import { AudioPlayer } from './AudioPlayer'
import { useTimeline } from '../timeline/useTimeline'

function Harness() {
  const timeline = useTimeline(12)
  return <AudioPlayer analysisId={analysisId} timeline={timeline} />
}

describe('AudioPlayer', () => {
  it('handles rejected play requests without showing a false playing state', async () => {
    const user = userEvent.setup()
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')!
    const play = vi
      .spyOn(media, 'play')
      .mockRejectedValue(new DOMException('Not allowed', 'NotAllowedError'))
    await user.click(screen.getByRole('button', { name: '播放音频' }))
    expect(play).toHaveBeenCalledOnce()
    expect(await screen.findByText(/播放未能开始/)).toBeVisible()
    expect(screen.getByRole('button', { name: '播放音频' })).toBeVisible()
  })

  it('synchronizes native pause, end, volume and bounded skip controls', async () => {
    const user = userEvent.setup()
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')!
    fireEvent.playing(media)
    expect(screen.getByRole('button', { name: '暂停音频' })).toBeVisible()
    fireEvent.pause(media)
    expect(screen.getByRole('button', { name: '播放音频' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: '后退 5 秒' }))
    expect(media.currentTime).toBe(0)
    fireEvent.change(screen.getByRole('slider', { name: '音频播放进度' }), {
      target: { value: '11' },
    })
    await user.click(screen.getByRole('button', { name: '前进 5 秒' }))
    expect(media.currentTime).toBe(12)
    fireEvent.change(screen.getByRole('slider', { name: '音量' }), {
      target: { value: '0.4' },
    })
    expect(media.volume).toBe(0.4)
    fireEvent.ended(media)
    expect(screen.getByText('播放结束。')).toBeVisible()
    expect(container.querySelectorAll('audio')).toHaveLength(1)
  })
  it('uses the authorized Range endpoint and synchronizes media time', () => {
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')

    expect(media).toHaveAttribute('src', `/api/analyses/${analysisId}/audio`)
    if (!media) throw new Error('missing audio element')
    media.currentTime = 4.25
    fireEvent.timeUpdate(media)

    expect(screen.getByLabelText(/当前播放时间/)).toHaveTextContent('0:04')
  })

  it('explains on-demand decryption and reports buffering around seeks', () => {
    const { container } = render(<Harness />)
    const media = container.querySelector('audio')
    if (!media) throw new Error('missing audio element')

    expect(screen.getByText(/按需解密/)).toBeVisible()
    fireEvent.seeking(media)
    expect(screen.getByText(/正在读取所选位置/)).toBeVisible()
    fireEvent.seeked(media)
    expect(screen.getByText(/音频已就绪/)).toBeVisible()
  })
})
