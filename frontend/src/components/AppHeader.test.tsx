import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppHeader } from './AppHeader'

describe('AppHeader', () => {
  it('shows a restrained brand header before an analysis starts', () => {
    render(<AppHeader analysisActive={false} onStartAnother={vi.fn()} />)

    expect(screen.getByText('MuseEcho')).toBeVisible()
    expect(screen.getByText('让音乐结构清晰可见')).toBeVisible()
    expect(screen.queryByRole('button', { name: '新的分析' })).not.toBeInTheDocument()
  })

  it('exposes the start-another action only in an active analysis', async () => {
    const user = userEvent.setup()
    const onStartAnother = vi.fn()
    render(<AppHeader analysisActive onStartAnother={onStartAnother} />)

    await user.click(screen.getByRole('button', { name: '新的分析' }))
    expect(onStartAnother).toHaveBeenCalledTimes(1)
  })
})
