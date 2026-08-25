import { Button } from './Button'

export interface AppHeaderProps {
  analysisActive: boolean
  onStartAnother: () => void
}

export function AppHeader({ analysisActive, onStartAnother }: AppHeaderProps) {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <p className="brand">MuseEcho</p>
        <p className="app-header__tagline">让音乐结构清晰可见</p>
      </div>
      {analysisActive ? (
        <Button className="app-header__action" onClick={onStartAnother} variant="secondary">
          新的分析
        </Button>
      ) : (
        <p className="edition-mark">Evidence-led music analysis</p>
      )}
    </header>
  )
}
