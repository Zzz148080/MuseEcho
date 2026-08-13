import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { UploadAccepted } from '../../api/types'
import { UploadForm, validateFile } from './UploadForm'

const accepted: UploadAccepted = {
  analysis_id: '00000000-0000-4000-8000-000000000001',
  stage: 'queued',
  progress: 0,
}

describe('UploadForm', () => {
  it('uses an exact-suffix chooser and rejects adjacent MP4 and OGA formats', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onUpload = vi.fn().mockResolvedValue(accepted)
    render(<UploadForm onUpload={onUpload} />)

    const input = screen.getByLabelText(/音频文件/)
    expect(input).toHaveAttribute(
      'accept',
      '.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus',
    )

    for (const file of [
      new File(['video'], 'track.mp4', { type: 'audio/mp4' }),
      new File(['audio'], 'track.oga', { type: 'audio/ogg' }),
    ]) {
      await user.upload(input, file)
      expect(screen.getByRole('alert')).toHaveTextContent(/不支持.*音频格式/)
      expect(onUpload).not.toHaveBeenCalled()
    }
  })

  it.each([
    'track.wav',
    'track.mp3',
    'track.flac',
    'track.m4a',
    'track.aac',
    'track.ogg',
    'track.opus',
  ])('preflights the supported %s suffix as an upload candidate', (filename) => {
    expect(validateFile(new File(['audio'], filename))).toBeNull()
  })

  it('does not upload until legal-use and retention consent is checked', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn().mockResolvedValue(accepted)
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    const submit = screen.getByRole('button', { name: /开始分析/ })
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    expect(submit).toBeDisabled()

    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    expect(submit).toBeEnabled()
    await user.click(submit)

    expect(onUpload).toHaveBeenCalledTimes(1)
  })

  it('preflights the 30 MB limit before calling the server', async () => {
    const user = userEvent.setup({ applyAccept: false })
    const onUpload = vi.fn().mockResolvedValue(accepted)
    render(<UploadForm onUpload={onUpload} />)

    const oversized = new File(['audio'], 'track.mp3', { type: 'audio/mpeg' })
    Object.defineProperty(oversized, 'size', { value: 30 * 1024 * 1024 + 1 })
    await user.upload(screen.getByLabelText(/音频文件/), oversized)

    expect(screen.getByRole('alert')).toHaveTextContent(/不能超过 30 MB/)
  })

  it('shows only progress reported by the upload transport', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn(
      (_file: File, onProgress: (progress: number) => void) => {
        onProgress(0.5)
        return new Promise<UploadAccepted>(() => undefined)
      },
    )
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    expect(screen.getByRole('progressbar', { name: /上传进度/ })).toHaveValue(50)
  })

  it('separates completed upload bytes from pending backend validation', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn(
      (_file: File, onProgress: (progress: number) => void) => {
        onProgress(1)
        return new Promise<UploadAccepted>(() => undefined)
      },
    )
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    expect(screen.getByText(/上传完成，等待后端验证/)).toBeVisible()
    expect(screen.getByRole('button', { name: /等待后端验证/ })).toBeDisabled()
  })

  it('turns stable server codes into a recoverable accessible error', async () => {
    const user = userEvent.setup()
    const onUpload = vi
      .fn()
      .mockRejectedValue(new ApiError(422, 'invalid_audio', 'internal detail'))
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['bad'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /无法读取这个音频.*重新选择/i,
    )
    expect(screen.queryByText(/internal detail/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /开始分析/ })).toBeDisabled()
  })

  it('allows an explicit retry only for a known transient service error', async () => {
    const user = userEvent.setup()
    const onUpload = vi
      .fn()
      .mockRejectedValue(new ApiError(503, 'audio_tool_unavailable'))
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    const retry = await screen.findByRole('button', { name: /重试上传/ })
    expect(retry).toBeEnabled()
    await user.click(retry)
    expect(onUpload).toHaveBeenCalledTimes(2)
  })

  it('does not blindly duplicate an upload after an ambiguous network failure', async () => {
    const user = userEvent.setup()
    const onUpload = vi.fn().mockRejectedValue(new ApiError(0, 'network_error'))
    render(<UploadForm onUpload={onUpload} />)

    await user.upload(
      screen.getByLabelText(/音频文件/),
      new File(['RIFF'], 'track.wav', { type: 'audio/wav' }),
    )
    await user.click(screen.getByRole('checkbox', { name: /有权分析/ }))
    await user.click(screen.getByRole('checkbox', { name: /加密保留最长 24 小时/ }))
    await user.click(screen.getByRole('button', { name: /开始分析/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/避免创建重复任务/)
    expect(screen.getByRole('button', { name: /开始分析/ })).toBeDisabled()
  })

  it('keeps file labels unique when the form is reused', () => {
    render(
      <>
        <UploadForm />
        <UploadForm />
      </>,
    )

    const inputs = screen.getAllByLabelText(/音频文件/)
    expect(inputs[0].id).not.toBe(inputs[1].id)
  })
})
