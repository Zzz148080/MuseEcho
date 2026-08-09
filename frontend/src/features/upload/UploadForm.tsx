import { useId, useState, type ChangeEvent, type FormEvent } from 'react'
import { ApiError, uploadAnalysis, type UploadTransport } from '../../api/client'
import type { UploadAccepted } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorNotice } from '../../components/ErrorNotice'

const MAX_UPLOAD_BYTES = 30 * 1024 * 1024
const supportedExtensions = new Set(['wav', 'mp3'])

export interface UploadFormProps {
  onAccepted?: (accepted: UploadAccepted) => void
  onUpload?: UploadTransport
}

interface UploadErrorPresentation {
  title: string
  action: string
  retryable: boolean
}

export function UploadForm({
  onAccepted,
  onUpload = uploadAnalysis,
}: UploadFormProps) {
  const fileInputId = useId()
  const helpId = useId()
  const [file, setFile] = useState<File | null>(null)
  const [legalUse, setLegalUse] = useState(false)
  const [retention, setRetention] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [submissionError, setSubmissionError] =
    useState<UploadErrorPresentation | null>(null)

  const handleFile = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0] ?? null
    setFile(selected)
    setUploadProgress(null)
    setValidationError(selected ? validateFile(selected) : null)
    setSubmissionError(null)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (
      !file ||
      !legalUse ||
      !retention ||
      validationError ||
      uploading ||
      (submissionError && !submissionError.retryable)
    ) {
      return
    }
    setUploading(true)
    setUploadProgress(0)
    setSubmissionError(null)
    try {
      const accepted = await onUpload(file, setUploadProgress)
      setUploading(false)
      onAccepted?.(accepted)
    } catch (reason) {
      setSubmissionError(uploadErrorPresentation(reason))
      setUploadProgress(null)
      setUploading(false)
    }
  }

  const canSubmit = Boolean(
    file &&
      legalUse &&
      retention &&
      !validationError &&
      !uploading &&
      (!submissionError || submissionError.retryable),
  )
  const waitingForValidation = uploading && uploadProgress === 1

  return (
    <form className="upload-form" onSubmit={(event) => void submit(event)}>
      <div className="upload-form__field">
        <label className="field-label" htmlFor={fileInputId}>
          音频文件
        </label>
        <p className="field-help" id={helpId}>
          支持 WAV 或 MP3，文件最大 30 MB，音频最长 10 分钟。客户端预检仅用于尽早提示，最终以后端验证为准。
        </p>
        <input
          accept=".wav,.mp3,audio/wav,audio/mpeg"
          aria-describedby={helpId}
          disabled={uploading}
          id={fileInputId}
          name="file"
          onChange={handleFile}
          type="file"
        />
        <span className="file-selection" aria-live="polite">
          {file ? file.name : '尚未选择音频'}
        </span>
      </div>

      <fieldset className="consent-group" disabled={uploading}>
        <legend>上传确认</legend>
        <label className="check-row">
          <input
            checked={legalUse}
            onChange={(event) => setLegalUse(event.target.checked)}
            type="checkbox"
          />
          <span>我确认自己有权分析并上传此音频。</span>
        </label>
        <label className="check-row">
          <input
            checked={retention}
            onChange={(event) => setRetention(event.target.checked)}
            type="checkbox"
          />
          <span>我了解音频会加密保留最长 24 小时，之后自动删除，也可提前删除。</span>
        </label>
      </fieldset>

      {validationError ? (
        <ErrorNotice title={validationError} action="请修正后重新选择。" />
      ) : null}

      {submissionError ? (
        <ErrorNotice
          title={submissionError.title}
          action={submissionError.action}
        />
      ) : null}

      {uploadProgress !== null ? (
        <div className="upload-meter" aria-live="polite">
          <div className="upload-meter__label">
            <span>
              {waitingForValidation ? '上传完成，等待后端验证' : '上传进度'}
            </span>
            <span>{Math.round(uploadProgress * 100)}%</span>
          </div>
          <progress
            aria-label="上传进度"
            max={100}
            value={Math.round(uploadProgress * 100)}
          />
        </div>
      ) : null}

      <Button disabled={!canSubmit} type="submit">
        {waitingForValidation
          ? '等待后端验证'
          : uploading
            ? '正在上传'
            : submissionError?.retryable
              ? '重试上传'
              : '开始分析'}
      </Button>
    </form>
  )
}

function validateFile(file: File): string | null {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!supportedExtensions.has(extension)) return '仅支持 WAV 或 MP3 音频文件。'
  if (file.size > MAX_UPLOAD_BYTES) return '音频文件不能超过 30 MB。'
  if (file.size === 0) return '音频文件不能为空。'
  return null
}

function uploadErrorPresentation(reason: unknown): UploadErrorPresentation {
  const retryableAction = '可以保持当前文件并重试上传。'
  const reselectAction = '请修正问题后重新选择音频文件。'
  if (!(reason instanceof ApiError)) {
    return {
      title: '上传未完成。',
      action: '无法确认服务器是否已接收请求。为避免创建重复任务，请重新选择文件后再试。',
      retryable: false,
    }
  }

  const retryable: Record<string, string> = {
    audio_decode_timeout: '音频验证超时。',
    audio_tool_unavailable: '音频分析服务暂时不可用。',
  }
  if (reason.code in retryable) {
    return {
      title: retryable[reason.code],
      action: retryableAction,
      retryable: true,
    }
  }

  if (reason.code === 'network_error') {
    return {
      title: '网络连接中断。',
      action: '服务器可能已收到请求。为避免创建重复任务，请重新选择文件后再试。',
      retryable: false,
    }
  }

  const nonRetryable: Record<string, string> = {
    upload_too_large: '音频文件不能超过 30 MB。',
    unsupported_audio: '仅支持 WAV 或 MP3 音频文件。',
    invalid_audio: '无法读取这个音频。',
    audio_too_long: '音频时长不能超过 10 分钟。',
    upload_aborted: '上传已中止。',
    invalid_server_response: '服务返回了无法识别的响应。',
  }
  return {
    title: nonRetryable[reason.code] ?? '上传未完成。',
    action: reselectAction,
    retryable: false,
  }
}

export { MAX_UPLOAD_BYTES, uploadErrorPresentation, validateFile }
