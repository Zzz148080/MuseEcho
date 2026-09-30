export type WorkspaceView = 'overview' | 'map' | 'deep'

export interface WorkspaceNavigationProps {
  current: WorkspaceView
  onChange: (next: WorkspaceView) => void
}

const items: ReadonlyArray<{
  index: string
  label: string
  note: string
  view: WorkspaceView
}> = [
  { index: '01', label: '歌曲概览', note: '播放与关键事实', view: 'overview' },
  { index: '02', label: '结构地图', note: '时间轴与和弦', view: 'map' },
  { index: '03', label: '深入分析', note: '节奏、调性与动态', view: 'deep' },
]

export function WorkspaceNavigation({
  current,
  onChange,
}: WorkspaceNavigationProps) {
  return (
    <nav aria-label="分析功能" className="workspace-nav">
      {items.map((item) => (
        <button
          aria-current={current === item.view ? 'page' : undefined}
          className="workspace-nav__item"
          key={item.view}
          onClick={() => onChange(item.view)}
          type="button"
        >
          <span className="workspace-nav__index" aria-hidden="true">
            {item.index}
          </span>
          <span>
            <strong>{item.label}</strong>
            <small>{item.note}</small>
          </span>
        </button>
      ))}
    </nav>
  )
}
