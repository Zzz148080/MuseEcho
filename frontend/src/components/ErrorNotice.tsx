export interface ErrorNoticeProps {
  action: string
  title: string
}

export function ErrorNotice({ action, title }: ErrorNoticeProps) {
  return (
    <div className="error-notice" role="alert">
      <p className="error-notice__title">{title}</p>
      <p className="error-notice__action">{action}</p>
    </div>
  )
}
