import type { JobStage } from '../../types/job'

const statusLabels = {
  pending: 'Chờ xử lý',
  running: 'Đang chạy',
  completed: 'Hoàn tất',
  failed: 'Thất bại',
  skipped: 'Đã bỏ qua',
}

function formatTime(seconds: number) {
  return seconds ? `${seconds} giây` : '—'
}

export function PipelineProgress({ stages }: { stages: JobStage[] }) {
  const completed = stages.filter((stage) => stage.status === 'completed').length
  return (
    <section className="panel pipeline-panel" aria-labelledby="pipeline-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">TIẾN TRÌNH</span>
          <h2 id="pipeline-title">Quy trình sản xuất</h2>
        </div>
        <span className="progress-count">{completed}/{stages.length} bước</span>
      </div>
      <div className="progress-track" aria-hidden="true">
        <span style={{ width: `${(completed / stages.length) * 100}%` }} />
      </div>
      <ol className="stage-list">
        {stages.map((stage, index) => (
          <li className={`stage-row ${stage.status}`} key={stage.id}>
            <span className="stage-marker" aria-hidden="true">
              {stage.status === 'completed' ? '✓' : stage.status === 'failed' ? '!' : index + 1}
            </span>
            <div className="stage-copy">
              <strong>{stage.name}</strong>
              <span>{stage.description}</span>
            </div>
            <span className={`status-pill ${stage.status}`}>{statusLabels[stage.status]}</span>
            <time>{formatTime(stage.elapsedSeconds)}</time>
          </li>
        ))}
      </ol>
    </section>
  )
}
