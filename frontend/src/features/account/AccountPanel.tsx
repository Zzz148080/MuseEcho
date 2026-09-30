import { useEffect, useRef, useState, type FormEvent } from 'react'
import {
  accountConfig, currentAccount, deleteAccount, exportLibrary, getProfile, getSaved,
  listSaved, localTestMailLink, login, logout, register, removeSaved, requestPasswordReset,
  resendVerification, resetPassword, setProfileEnabled, updateSaved, verifyEmail,
  type AccountUser, type MusicProfile, type SavedDetail, type SavedSong,
} from '../../api/account'
import { ApiError } from '../../api/client'
import { Button } from '../../components/Button'
import { Icon } from '../../components/Icon'
import { AuthDialog, type AuthMode } from './AuthDialog'

interface Props {
  onAccountChange: (user: AccountUser | null) => void
  onPanelOpenChange?: (open: boolean) => void
  onOpenSaved: (detail: SavedDetail) => void
  refreshKey: number
}

type AccountView = 'library' | 'profile'

export function AccountPanel({ onAccountChange, onPanelOpenChange, onOpenSaved, refreshKey }: Props) {
  const [user, setUser] = useState<AccountUser | null>(null)
  const [available, setAvailable] = useState(false)
  const [mode, setMode] = useState<AuthMode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [deletePassword, setDeletePassword] = useState('')
  const [resetToken, setResetToken] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<AccountView>('library')
  const [authOpen, setAuthOpen] = useState(false)
  const [previewLink, setPreviewLink] = useState<string | null>(null)
  const [songs, setSongs] = useState<SavedSong[]>([])
  const [total, setTotal] = useState(0)
  const [savedCount, setSavedCount] = useState(0)
  const [offset, setOffset] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('newest')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [expandedSongId, setExpandedSongId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [profile, setProfile] = useState<MusicProfile | null>(null)
  const handledVerification = useRef<string | null>(null)

  useEffect(() => {
    let alive = true
    void Promise.all([accountConfig(), currentAccount()]).then(([config, account]) => {
      if (!alive) return
      setAvailable(config.registration_available)
      setUser(account)
      onAccountChange(account)
    }).catch(() => { if (alive) setError('暂时无法连接账号服务。') })
    const handleFragment = () => {
      const url = new URL(window.location.href)
      const fragment = new URLSearchParams(url.hash.slice(1))
      const verify = fragment.get('verify')
      const reset = fragment.get('reset')
      if (verify && handledVerification.current !== verify) {
        handledVerification.current = verify
        setAuthOpen(true)
        setError(''); setNotice(''); setPreviewLink(null)
        void verifyEmail(verify).then(() => {
          if (alive) setNotice('邮箱验证完成，现在可以登录。')
        }).catch(() => { if (alive) setError('验证链接无效或已过期。') }).finally(() => {
          url.hash = ''
          window.history.replaceState(null, '', url)
        })
      }
      if (reset) {
        setResetToken(reset); setMode('reset'); setAuthOpen(true)
        setError(''); setNotice(''); setPreviewLink(null)
      }
    }
    handleFragment()
    window.addEventListener('hashchange', handleFragment)
    return () => { alive = false; window.removeEventListener('hashchange', handleFragment) }
  }, [onAccountChange])

  useEffect(() => {
    if (!user || !open) return
    let alive = true
    void Promise.all([listSaved(offset, query, sort), getProfile()]).then(([page, nextProfile]) => {
      if (!alive) return
      setSongs(page.items)
      setTotal(page.total)
      setSavedCount(page.saved_count)
      setProfile(nextProfile)
    }).catch(() => { if (alive) setError('歌曲库暂时无法读取，请重试。') })
    return () => { alive = false }
  }, [user, open, offset, query, sort, refreshKey])

  useEffect(() => {
    if (!open) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [open])

  useEffect(() => {
    onPanelOpenChange?.(open && user !== null)
    return () => onPanelOpenChange?.(false)
  }, [onPanelOpenChange, open, user])

  const reload = async () => {
    const [page, nextProfile] = await Promise.all([listSaved(offset, query, sort), getProfile()])
    setSongs(page.items)
    setTotal(page.total)
    setSavedCount(page.saved_count)
    setProfile(nextProfile)
  }

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError(''); setNotice('')
    setPreviewLink(null)
    try {
      if (mode === 'login') {
        const account = await login(email, password)
        setUser(account); onAccountChange(account); setPassword('')
        setAuthOpen(false)
        setOpen(true)
        setNotice('已登录，你可以保存分析到私人歌曲库。')
      } else if (mode === 'register') {
        await register(email, password)
        setPassword(''); setMode('login')
        setNotice('如果邮箱可用，验证链接已发送。完成验证后登录。')
        setPreviewLink(await localTestMailLink(email))
      } else if (mode === 'forgot') {
        await requestPasswordReset(email)
        setNotice('如果账号存在，重置链接已发送。请检查收件箱及垃圾邮件。')
        setPreviewLink(await localTestMailLink(email))
      } else if (resetToken) {
        await resetPassword(resetToken, password)
        setResetToken(null); setPassword(''); setMode('login')
        setUser(null); onAccountChange(null); setOpen(false)
        const url = new URL(window.location.href)
        url.hash = ''
        window.history.replaceState(null, '', url)
        setNotice('密码已更新，请重新登录。')
      }
    } catch (reason) { setError(message(reason)) }
    finally { setBusy(false) }
  }

  const changeMode = (next: AuthMode) => {
    setMode(next); setError(''); setNotice(''); setPassword(''); setPreviewLink(null)
    if (next !== 'reset') setResetToken(null)
  }

  const resend = async () => {
    if (busy || !email.trim()) return
    setBusy(true); setError(''); setNotice(''); setPreviewLink(null)
    try {
      await resendVerification(email)
      setNotice('如果邮箱可用，验证链接已发送。')
      setPreviewLink(await localTestMailLink(email))
    } catch (reason) { setError(message(reason)) }
    finally { setBusy(false) }
  }

  const signOut = async () => {
    setBusy(true); setError('')
    try {
      await logout(); setUser(null); onAccountChange(null); setOpen(false)
      setSongs([]); setProfile(null); setNotice('已退出登录。')
    } catch (reason) { setError(message(reason)) }
    finally { setBusy(false) }
  }

  const openView = (nextView: AccountView) => {
    setView(nextView)
    if (user) {
      setOpen(true)
      return
    }
    setMode('login')
    setAuthOpen(true)
  }

  const changePreference = async (song: SavedSong, preference: SavedSong['preference']) => {
    setError('')
    try { await updateSaved(song.id, { preference }); await reload() }
    catch (reason) { setError(message(reason)) }
  }

  const remove = async (song: SavedSong) => {
    if (!window.confirm(`从私人歌曲库删除“${song.title}”？这不会恢复或延长原音频。`)) return
    setError('')
    try { await removeSaved(song.id); await reload() }
    catch (reason) { setError(message(reason)) }
  }

  const rename = async (song: SavedSong) => {
    setError('')
    try {
      await updateSaved(song.id, { title: draftTitle.trim() })
      setEditingId(null)
      setExpandedSongId(null)
      await reload()
    } catch (reason) { setError(message(reason)) }
  }

  const openSong = async (song: SavedSong) => {
    setError('')
    try { onOpenSaved(await getSaved(song.id)); setOpen(false) }
    catch (reason) { setError(message(reason)) }
  }

  const exportData = async () => {
    setError('')
    try {
      const data = await exportLibrary()
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = 'museecho-library.json'; anchor.click()
      URL.revokeObjectURL(url)
    } catch (reason) { setError(message(reason)) }
  }

  const eraseAccount = async () => {
    if (!deletePassword || !window.confirm('确定注销账号？私人歌曲库和音乐画像会永久删除。')) return
    setError('')
    try { await deleteAccount(deletePassword); setDeletePassword(''); setUser(null); onAccountChange(null); setOpen(false); setNotice('账号已注销。') }
    catch (reason) { setError(message(reason)) }
  }

  return (
    <section className="account-panel" aria-label="账号和私人歌曲库">
      {!open ? <nav className="account-desktop-rail" aria-label="音乐空间导航">
        <button
          aria-controls="account-sidebar"
          aria-expanded={open}
          aria-label={user ? '打开音乐空间侧边栏' : '登录 / 注册'}
          className="account-rail-button account-rail-button--brand account-sidebar-trigger"
          onClick={() => user ? setOpen((value) => !value) : setAuthOpen(true)}
          type="button"
        >
          <Icon name={user ? 'panel' : 'user'} />
          <span>{user ? '音乐空间' : '登录 / 注册'}</span>
        </button>
      </nav> : null}

      <nav className="account-mobile-nav" aria-label="主要页面">
        <button aria-current={!open ? 'page' : undefined} onClick={() => setOpen(false)} type="button">
          <Icon name="music" /><span>分析</span>
        </button>
        <button aria-current={open && view === 'library' ? 'page' : undefined} onClick={() => openView('library')} type="button">
          <Icon name="library" /><span>歌曲库</span>
        </button>
        <button aria-current={open && view === 'profile' ? 'page' : undefined} onClick={() => openView('profile')} type="button">
          <Icon name="user" /><span>个人</span>
        </button>
      </nav>

      {user && open ? (
          <aside className="account-sidebar" id="account-sidebar" aria-label="我的音乐空间">
            <header className="account-sidebar__header">
              <div className="account-sidebar__brand">
                <span><Icon name={view === 'library' ? 'library' : 'sparkle'} /></span>
                <div>
                  <p className="eyebrow">用户记忆</p>
                  <h2>我的音乐空间</h2>
                </div>
              </div>
              <button aria-label="收起" className="account-sidebar__close" onClick={() => setOpen(false)} type="button">
                <Icon name="close" />
              </button>
            </header>

            <div className="account-sidebar__identity">
              <span className="account-avatar">{user.email.slice(0, 1).toUpperCase()}</span>
              <div><strong>已登录</strong><span>{user.email}</span><span className="sr-only">已登录：{user.email}</span></div>
              <span className="account-capacity">{savedCount}/100</span>
            </div>

            <nav className="account-sidebar__tabs" aria-label="音乐空间页面">
              <button aria-current={view === 'library' ? 'page' : undefined} onClick={() => setView('library')} type="button">
                <Icon name="library" /><span>歌曲库</span>
                <small>{savedCount} 首</small>
              </button>
              <button aria-current={view === 'profile' ? 'page' : undefined} onClick={() => setView('profile')} type="button">
                <Icon name="user" /><span>个人主页</span>
                <small>偏好与账户</small>
              </button>
            </nav>

            <div className="account-sidebar__scroll">
              {notice && !authOpen ? <p role="status" className="account-panel__notice">{notice}</p> : null}
              {error && !authOpen ? <p role="alert" className="account-panel__error">{error}</p> : null}

              {view === 'library' ? (
                <section className="account-sidebar__page" aria-labelledby="library-title">
                  <div className="account-page-heading">
                    <div><p className="eyebrow">私人数据库</p><h3 id="library-title">歌曲库</h3></div>
                    <span>{total} 首结果</span>
                  </div>
                  <p className="account-page-lead">私人保存 {savedCount} / 100 首。原音频最长保留 24 小时；到期后仍可复看已保存的分析。</p>
                  <form className="account-panel__filters" onSubmit={(event) => { event.preventDefault(); setOffset(0); setQuery(searchInput.trim()) }}>
                    <label className="account-search-field">
                      <span>搜索标题</span>
                      <span><Icon name="search" /><input value={searchInput} maxLength={80} onChange={(event) => setSearchInput(event.target.value)} /></span>
                    </label>
                    <label>排序<select value={sort} onChange={(event) => { setSort(event.target.value); setOffset(0) }}>
                      <option value="newest">最近保存</option><option value="oldest">最早保存</option><option value="title">按标题</option>
                    </select></label>
                    <Button type="submit" variant="secondary">搜索</Button>
                  </form>
                  {songs.length ? (
                    <ul className="account-song-list">{songs.map((song) => <li key={song.id}>
                      <div className="account-song-main">
                        <span className="account-song-note"><Icon name="music" /></span>
                        <div><strong>{song.title}</strong><small>{new Date(song.saved_at).toLocaleDateString('zh-CN')} · {song.preference === 'liked' ? '喜欢' : song.preference === 'disliked' ? '不喜欢' : '未标记偏好'}</small></div>
                      </div>
                      <div className="account-song-primary-actions">
                        <Button onClick={() => void openSong(song)}>查看分析</Button>
                        <button
                          aria-controls={`song-actions-${song.id}`}
                          aria-expanded={expandedSongId === song.id}
                          aria-label={`${song.title}的更多操作`}
                          className="account-song-more"
                          onClick={() => { setExpandedSongId((value) => value === song.id ? null : song.id); setEditingId(null) }}
                          type="button"
                        ><Icon name="more" /></button>
                      </div>
                      {expandedSongId === song.id ? <div className="account-song-secondary-actions" id={`song-actions-${song.id}`}>
                        {editingId === song.id ? <div className="account-song-rename"><input aria-label="新歌曲标题" value={draftTitle} maxLength={120} onChange={(event) => setDraftTitle(event.target.value)} /><Button disabled={!draftTitle.trim()} onClick={() => void rename(song)} variant="secondary">保存标题</Button><Button onClick={() => setEditingId(null)} variant="secondary">取消</Button></div> : <>
                          <label>我的偏好<select aria-label={`${song.title}的偏好`} value={song.preference} onChange={(event) => void changePreference(song, event.target.value as SavedSong['preference'])}>
                            <option value="unmarked">未标记</option><option value="liked">喜欢</option><option value="disliked">不喜欢</option>
                          </select></label>
                          <button className="account-text-action" onClick={() => { setEditingId(song.id); setDraftTitle(song.title) }} type="button">修改标题</button>
                          <button className="account-text-action account-text-action--danger" onClick={() => void remove(song)} type="button">删除保存</button>
                        </>}
                      </div> : null}
                    </li>)}</ul>
                  ) : (
                    <div className="account-empty-state"><Icon name="library" /><h4>还没有保存的分析</h4><p>完成一次真实分析后，可在工作台中逐首保存。</p></div>
                  )}
                  {total > 20 ? <div className="account-panel__pager">
                    <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))} variant="secondary">上一页</Button>
                    <span>{offset + 1}–{Math.min(total, offset + 20)} / {total}</span>
                    <Button disabled={offset + 20 >= total} onClick={() => setOffset(offset + 20)} variant="secondary">下一页</Button>
                  </div> : null}
                </section>
              ) : (
                <section className="account-sidebar__page" aria-labelledby="profile-title">
                  <div className="account-page-heading">
                    <div><p className="eyebrow">只属于你的音乐空间</p><h3 id="profile-title">个人主页</h3></div>
                  </div>
                  <div className="account-profile account-profile--sidebar">
                    <div><h4>音乐人格 · 偏好卡</h4><p>只根据你主动标记“喜欢”的真实歌曲生成，不作人格诊断。</p></div>
                    {profile ? <label className="account-toggle"><input type="checkbox" checked={profile.enabled} onChange={(event) => void setProfileEnabled(event.target.checked).then(setProfile).catch((reason) => setError(message(reason)))} /><span aria-hidden="true" />启用私人画像</label> : <p>正在读取偏好数据…</p>}
                    {profile?.enabled && (profile.tags.length ? <ul>{profile.tags.map((tag) => <li key={tag.name}><strong>{tag.name}</strong><span>{tag.basis} · {tag.sample_count} 首依据</span><details><summary>查看依据歌曲</summary><ul>{tag.sources.map((source) => <li key={source.id}>{source.title}</li>)}</ul></details></li>)}</ul> : <p>已喜欢 {profile.sample_count} 首；至少 5 首且数据足够可靠后才显示标签。</p>)}
                  </div>

                  <div className="account-data-card">
                    <span><Icon name="database" /></span>
                    <div><h4>数据与隐私</h4><p>私人保存 {savedCount}/100 首；分析音频最长保留 24 小时。</p></div>
                    <Button onClick={() => void exportData()} variant="secondary">导出我的数据</Button>
                  </div>

                  <div className="account-session-card">
                    <div><h4>登录与会话</h4><p>{user.email}</p></div>
                    <Button onClick={() => void signOut()} disabled={busy} variant="secondary">退出登录</Button>
                  </div>

                  <details className="account-danger-zone">
                    <summary><span><strong>注销账号</strong><small>永久删除账号与私人数据</small></span><Icon name="chevron" /></summary>
                    <div className="account-danger-zone__content">
                      <p>此操作不可恢复，将永久删除私人歌曲库和音乐画像。</p>
                      <label>确认当前密码<input type="password" autoComplete="current-password" value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} /></label>
                      <Button onClick={() => void eraseAccount()} disabled={!deletePassword} variant="danger">确认注销账号</Button>
                    </div>
                  </details>
                </section>
              )}
            </div>
          </aside>
      ) : null}

      {authOpen && (!user || mode === 'reset') && <AuthDialog mode={mode} onModeChange={changeMode} onClose={() => { setAuthOpen(false); setError(''); setNotice(''); setPreviewLink(null) }} onSubmit={(event) => void submit(event)} onResend={() => void resend()} email={email} onEmailChange={setEmail} password={password} onPasswordChange={setPassword} available={available} busy={busy} error={error} notice={notice} previewLink={previewLink} />}
    </section>
  )
}

function message(reason: unknown): string {
  if (!(reason instanceof ApiError)) return '请求未完成，请检查网络后重试。'
  const messages: Record<string, string> = {
    invalid_credentials: '邮箱、密码或验证状态不正确。', invalid_email: '请输入有效邮箱。',
    invalid_password: '密码需为 12–128 个字符。', invalid_token: '链接无效或已过期。',
    rate_limited: '操作过于频繁，请 15 分钟后重试。', email_not_configured: '邮件服务尚未配置。',
    unauthorized: '登录已过期，请重新登录。', csrf_unavailable: '安全校验已失效，请重新登录。',
    network_error: '网络连接中断，请重试。', email_delivery_failed: '邮件暂时无法发送，请稍后重试。',
  }
  return messages[reason.code] ?? '请求未完成，请重试。'
}
