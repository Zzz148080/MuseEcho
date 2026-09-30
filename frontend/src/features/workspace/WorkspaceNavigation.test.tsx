import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { WorkspaceNavigation } from './WorkspaceNavigation'

describe('WorkspaceNavigation', () => {
  it('labels the three result views and marks the current view', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<WorkspaceNavigation current="overview" onChange={onChange} />)

    expect(screen.getByRole('navigation', { name: '分析功能' })).toBeVisible()
    expect(screen.getByRole('button', { name: /歌曲概览/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
    await user.click(screen.getByRole('button', { name: /结构地图/ }))
    expect(onChange).toHaveBeenCalledWith('map')
    await user.click(screen.getByRole('button', { name: /深入分析/ }))
    expect(onChange).toHaveBeenCalledWith('deep')
  })
})
