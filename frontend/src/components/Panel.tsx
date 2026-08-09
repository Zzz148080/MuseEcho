import { useId, type ReactNode } from 'react'

export interface PanelProps {
  children: ReactNode
  className?: string
  eyebrow?: string
  title: string
}

export function Panel({ children, className = '', eyebrow, title }: PanelProps) {
  const titleId = `panel-${useId().replaceAll(':', '')}`
  const classes = ['panel', className].filter(Boolean).join(' ')

  return (
    <section aria-labelledby={titleId} className={classes}>
      <header className="panel__header">
        <h2 className="panel__title" id={titleId}>
          {title}
        </h2>
        {eyebrow ? <span className="edition-mark">{eyebrow}</span> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}
