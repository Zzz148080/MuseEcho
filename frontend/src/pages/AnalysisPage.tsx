import { Panel } from '../components/Panel'

export function AnalysisPage() {
  return (
    <div className="app-shell">
      <header className="masthead">
        <p className="brand">MuseEcho</p>
        <p className="edition-mark">Evidence-led music analysis</p>
      </header>

      <main
        aria-label="MuseEcho 音乐解析工作区"
        className="analysis-workspace"
      >
        <section aria-labelledby="workspace-title" className="workspace-intro">
          <div>
            <p className="eyebrow">聆听证据，而非猜测</p>
            <h1 className="display-title" id="workspace-title">
              看见音乐的结构
            </h1>
          </div>
          <p className="intro-copy">
            MuseEcho 将可验证的音频证据整理到同一条时间线上。证据不足时，结果会明确标记为 unknown。
          </p>
        </section>

        <Panel className="workflow-panel" eyebrow="等待音频" title="分析流程">
          <div className="empty-workflow">
            <div>
              <h2 className="empty-workflow__title">开始解析</h2>
              <p className="empty-workflow__copy">
                尚未选择音频。上传入口将在这里提供文件限制、隐私与保留规则，然后才会开始真实分析。
              </p>
            </div>
            <ol className="workflow-steps" aria-label="解析步骤">
              <li>选择与验证音频</li>
              <li>提取可复核证据</li>
              <li>沿时间轴呈现结果</li>
            </ol>
          </div>
        </Panel>
      </main>
    </div>
  )
}
