import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { analysisId } from '../../test/analysisFixture'
import { RetentionPanel, retentionText } from './RetentionPanel'

describe('RetentionPanel', () => {
  async function openDataManagement(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByText('管理分析数据', { selector: 'summary' }))
  }

  it('does not present a still-active server retention window as zero minutes', () => {
    const now = Date.parse('2026-08-09T23:59:01Z')
    const expiry = Date.parse('2026-08-10T00:00:00Z')

    expect(retentionText(expiry, now)).toContain('剩余不足 1 分钟')
  })

  it('uses server expiry and requires explicit confirmation before deletion', async () => {
    const user = userEvent.setup()
    const remove = vi.fn().mockResolvedValue(undefined)
    const onDeleted = vi.fn()
    render(
      <RetentionPanel
        analysisId={analysisId}
        clock={() => Date.parse('2026-08-09T23:00:00Z')}
        expiresAt="2026-08-10T00:00:00Z"
        onDeleted={onDeleted}
        remove={remove}
      />,
    )

    await openDataManagement(user)
    expect(screen.getByText(/剩余 1 小时 0 分钟/)).toBeVisible()
    const deleteButton = screen.getByRole('button', { name: '永久删除分析' })
    expect(deleteButton).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /了解删除不可恢复/ }))
    expect(deleteButton).toBeEnabled()
    await user.click(deleteButton)

    expect(remove).toHaveBeenCalledWith(analysisId)
    expect(onDeleted).toHaveBeenCalledOnce()
  })

  it('does not send deletion after the server expiry has passed', async () => {
    const user = userEvent.setup()
    const remove = vi.fn()
    render(
      <RetentionPanel
        analysisId={analysisId}
        clock={() => Date.parse('2026-08-10T00:00:01Z')}
        expiresAt="2026-08-10T00:00:00Z"
        onDeleted={vi.fn()}
        remove={remove}
      />,
    )

    await openDataManagement(user)
    expect(screen.getByText(/保留期限已到/)).toBeVisible()
    expect(screen.getByRole('button', { name: '永久删除分析' })).toBeDisabled()
    expect(remove).not.toHaveBeenCalled()
  })

  it('keeps the analysis visible after a failed deletion and retries explicitly', async () => {
    const user = userEvent.setup()
    const remove = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(0, 'network_error'))
      .mockResolvedValueOnce(undefined)
    const onDeleted = vi.fn()
    render(
      <RetentionPanel
        analysisId={analysisId}
        clock={() => Date.parse('2026-08-09T23:00:00Z')}
        expiresAt="2026-08-10T00:00:00Z"
        onDeleted={onDeleted}
        remove={remove}
      />,
    )

    await openDataManagement(user)
    await user.click(screen.getByRole('checkbox', { name: /了解删除不可恢复/ }))
    await user.click(screen.getByRole('button', { name: '永久删除分析' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/网络连接中断.*不会自动重试/)
    expect(onDeleted).not.toHaveBeenCalled()
    expect(remove).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: '重新尝试删除' }))
    expect(remove).toHaveBeenCalledTimes(2)
    expect(onDeleted).toHaveBeenCalledOnce()
  })
})
