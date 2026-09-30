import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Button } from '../../components/Button'

export type AuthMode = 'login' | 'register' | 'forgot' | 'reset'

interface Props {
  mode: AuthMode
  onModeChange: (mode: AuthMode) => void
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onResend: () => void
  email: string
  onEmailChange: (value: string) => void
  password: string
  onPasswordChange: (value: string) => void
  available: boolean
  busy: boolean
  error: string
  notice: string
  previewLink: string | null
}

const titles: Record<AuthMode, string> = {
  login: '欢迎回到音乐空间',
  register: '创建你的音乐空间',
  forgot: '找回账号密码',
  reset: '设置新密码',
}

export function AuthDialog(props: Props) {
  const { mode, onModeChange, onClose, onSubmit, onResend, email, onEmailChange,
    password, onPasswordChange, available, busy, error, notice, previewLink } = props
  const [confirmation, setConfirmation] = useState('')
  const [visible, setVisible] = useState(false)
  const dialog = useRef<HTMLDivElement>(null)
  const firstField = useRef<HTMLInputElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const returnFocus = useRef<HTMLElement | null>(null)

  useEffect(() => {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const frame = requestAnimationFrame(() => (firstField.current ?? closeButton.current)?.focus())
    return () => {
      cancelAnimationFrame(frame)
      document.body.style.overflow = previousOverflow
      returnFocus.current?.focus()
    }
  }, [])

  useEffect(() => { setConfirmation(''); setVisible(false); firstField.current?.focus() }, [mode])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && !busy) { onClose(); return }
    if (event.key !== 'Tab' || !dialog.current) return
    const controls = [...dialog.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), a[href]')]
      .filter((control) => control.getClientRects().length > 0)
    if (!controls.length) return
    const first = controls[0]
    const last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }

  const needsPassword = mode !== 'forgot'
  const confirmPassword = mode === 'register' || mode === 'reset'
  return createPortal(
    <div className="auth-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}>
      <div className="auth-dialog" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="auth-title" onKeyDown={onKeyDown}>
        <button ref={closeButton} className="auth-dialog__close" type="button" aria-label="关闭账号窗口" onClick={onClose} disabled={busy}>×</button>
        <div className="auth-dialog__glow" aria-hidden="true" />
        <p className="eyebrow">MUSEECHO · USER MEMORY</p>
        <h2 id="auth-title">{titles[mode]}</h2>
        <p className="auth-dialog__lead">{mode === 'login' ? '接着收藏你的声音轨迹。' : mode === 'register' ? '为喜欢的分析留一个只属于你的地方。' : mode === 'forgot' ? '输入注册邮箱，我们会发送一次性重置链接。' : '新密码设置完成后，原有登录会话将退出。'}</p>
        {mode !== 'reset' && <div className="auth-dialog__tabs" aria-label="账号操作">
          <button type="button" className={mode === 'login' ? 'is-active' : ''} onClick={() => onModeChange('login')} disabled={busy}>登录</button>
          <button type="button" className={mode === 'register' ? 'is-active' : ''} onClick={() => onModeChange('register')} disabled={busy || !available}>注册</button>
        </div>}
        {!available && mode === 'register' && <p className="auth-dialog__hint">当前未配置邮件服务，暂无法注册。已有账号仍可登录。</p>}
        <form className="auth-dialog__form" onSubmit={onSubmit}>
          {mode !== 'reset' && <label>邮箱地址<input ref={firstField} autoComplete="email" type="email" inputMode="email" value={email} onChange={(event) => onEmailChange(event.target.value)} required disabled={busy} /></label>}
          {needsPassword && <label>{mode === 'reset' ? '新密码' : '密码'}<span className="auth-dialog__password"><input aria-label={mode === 'reset' ? '新密码' : '密码'} ref={mode === 'reset' ? firstField : undefined} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} type={visible ? 'text' : 'password'} minLength={mode === 'login' ? undefined : 12} maxLength={128} value={password} onChange={(event) => onPasswordChange(event.target.value)} required disabled={busy} /><button type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? '隐藏密码' : '显示密码'}>{visible ? '隐藏' : '显示'}</button></span></label>}
          {confirmPassword && <label>确认新密码<input autoComplete="new-password" type={visible ? 'text' : 'password'} minLength={12} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required disabled={busy} /></label>}
          {confirmPassword && <p className="auth-dialog__hint">密码需为 12–128 个字符。</p>}
          {confirmPassword && confirmation && confirmation !== password && <p className="auth-dialog__error" role="alert">两次输入的密码不一致。</p>}
          {error && <p className="auth-dialog__error" role="alert">{error}</p>}
          {notice && <p className="auth-dialog__notice" role="status">{notice}</p>}
          {previewLink && <p className="auth-dialog__preview"><a href={previewLink}>打开本地测试邮件链接</a><span>仅在此电脑的测试预览中可用</span></p>}
          <Button type="submit" disabled={busy || (mode === 'register' && !available) || (confirmPassword && confirmation !== password)}>{busy ? '正在处理…' : mode === 'login' ? '登录账号' : mode === 'register' ? '创建账号' : mode === 'forgot' ? '发送重置链接' : '更新密码'}</Button>
        </form>
        <div className="auth-dialog__footer">
          {mode === 'login' && <><button type="button" onClick={() => onModeChange('forgot')} disabled={busy}>忘记密码？</button><button type="button" onClick={onResend} disabled={busy || !email.trim() || !available}>重发验证邮件</button></>}
          {(mode === 'forgot' || mode === 'reset') && <button type="button" onClick={() => onModeChange('login')} disabled={busy}>返回登录</button>}
        </div>
      </div>
    </div>,
    document.body,
  )
}
