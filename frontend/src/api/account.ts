import { ApiError, parseAnalysisResult } from './client'
import type { AnalysisResult } from './types'

export interface AccountUser { id: string; email: string }
export interface SavedSong {
  id: string
  original_analysis_id: string
  title: string
  preference: 'unmarked' | 'liked' | 'disliked'
  saved_at: string
}
export interface SavedDetail extends SavedSong {
  analysis: AnalysisResult
  audio_available: boolean
}
export interface ProfileTag {
  name: string
  basis: string
  sample_count: number
  song_ids: string[]
  version: string
  sources: { id: string; title: string }[]
}
export interface MusicProfile {
  enabled: boolean
  sample_count: number
  minimum_samples?: number
  version?: string
  tags: ProfileTag[]
}

function cookieValue(name: string): string | undefined {
  return document.cookie.split(';').map((part) => part.trim())
    .find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1)
}

function csrf(): string {
  const value = cookieValue('museecho_user_csrf')
  if (!value || !/^[A-Za-z0-9_-]{1,200}$/.test(value)) {
    throw new ApiError(0, 'csrf_unavailable')
  }
  return value
}

async function request(path: string, method = 'GET', payload?: unknown, authenticated = false): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(payload === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...(authenticated && method !== 'GET' ? { 'X-User-CSRF-Token': csrf() } : {}),
      },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    })
  } catch (error) {
    if (error instanceof ApiError) throw error
    throw new ApiError(0, 'network_error')
  }
  const body: unknown = response.status === 204 ? null : await response.json().catch(() => null)
  if (!response.ok) {
    const entry = body && typeof body === 'object' && 'error' in body ? body.error : null
    const code = entry && typeof entry === 'object' && 'code' in entry && typeof entry.code === 'string'
      ? entry.code : response.status === 401 ? 'unauthorized' : 'request_failed'
    throw new ApiError(response.status, code)
  }
  return body
}

export async function accountConfig(): Promise<{ registration_available: boolean }> {
  return await request('/api/account/config') as { registration_available: boolean }
}
export async function currentAccount(): Promise<AccountUser | null> {
  // The CSRF cookie is issued and cleared with the HttpOnly session cookie.
  // Avoid an expected 401 request (and its browser console noise) for visitors
  // who have never signed in or have explicitly signed out.
  if (!cookieValue('museecho_user_csrf')) return null
  try { return await request('/api/account/me') as AccountUser }
  catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}
export async function register(email: string, password: string): Promise<void> {
  await request('/api/account/register', 'POST', { email, password })
}
export async function resendVerification(email: string): Promise<void> {
  await request('/api/account/resend-verification', 'POST', { email })
}
export async function verifyEmail(token: string): Promise<void> {
  await request('/api/account/verify', 'POST', { token })
}
export async function login(email: string, password: string): Promise<AccountUser> {
  return await request('/api/account/login', 'POST', { email, password }) as AccountUser
}
export async function logout(): Promise<void> {
  await request('/api/account/logout', 'POST', undefined, true)
}
export async function requestPasswordReset(email: string): Promise<void> {
  await request('/api/account/request-reset', 'POST', { email })
}
export async function resetPassword(token: string, password: string): Promise<void> {
  await request('/api/account/reset-password', 'POST', { token, password })
}

export async function localTestMailLink(email: string): Promise<string | null> {
  try {
    const response = await fetch(`/__test/mail-link?email=${encodeURIComponent(email)}`, { credentials: 'same-origin' })
    if (!response.ok) return null
    const body: unknown = await response.json()
    return body && typeof body === 'object' && 'link' in body && typeof body.link === 'string'
      && new URL(body.link).origin === window.location.origin ? body.link : null
  } catch { return null }
}
export async function deleteAccount(password: string): Promise<void> {
  await request('/api/account/me', 'DELETE', { password }, true)
}
export async function listSaved(offset = 0, query = '', sort = 'newest'): Promise<{ items: SavedSong[]; total: number; saved_count: number; limit: number }> {
  const params = new URLSearchParams({ offset: String(offset), limit: '20', q: query, sort })
  return await request(`/api/library?${params}`) as { items: SavedSong[]; total: number; saved_count: number; limit: number }
}
export async function saveAnalysis(analysisId: string, title: string): Promise<SavedSong> {
  return await request(`/api/analyses/${analysisId}/save`, 'POST', { title }, true) as SavedSong
}
export async function getSaved(id: string): Promise<SavedDetail> {
  const data = await request(`/api/library/${id}`) as SavedDetail
  return { ...data, analysis: parseAnalysisResult(data.analysis) }
}
export async function updateSaved(id: string, change: { title?: string; preference?: SavedSong['preference'] }): Promise<SavedSong> {
  return await request(`/api/library/${id}`, 'PATCH', change, true) as SavedSong
}
export async function removeSaved(id: string): Promise<void> {
  await request(`/api/library/${id}`, 'DELETE', undefined, true)
}
export async function getProfile(): Promise<MusicProfile> {
  return await request('/api/library/profile') as MusicProfile
}
export async function setProfileEnabled(enabled: boolean): Promise<MusicProfile> {
  return await request('/api/library/profile', 'PATCH', { enabled }, true) as MusicProfile
}
export async function exportLibrary(): Promise<unknown> {
  return await request('/api/library/export')
}
