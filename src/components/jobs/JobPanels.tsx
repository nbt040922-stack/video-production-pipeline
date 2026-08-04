import type { EngineStatus, OutputMetadata, SourceMetadata } from '../../types/job'
import { VideoPreview } from '../video/VideoPreview'

const statusLabels = {
  pending: 'Chờ xử lý',
  running: 'Đang chạy',
  completed: 'Hoàn tất',
  failed: 'Thất bại',
  skipped: 'Đã bỏ qua',
}

export function SourcePreview({ source }: { source: SourceMetadata }) {
  return (
    <section className="panel source-card" aria-labelledby="source-title">
      <VideoPreview label="Xem trước video YouTube nguồn" src={source.thumbnailUrl} />
      <div className="source-details">
        <div className="source-ready"><span /> Nguồn hợp lệ</div>
        <h2 id="source-title">{source.title}</h2>
        <p>{source.channel}</p>
        <dl className="metadata-row">
          <div><dt>Thời lượng</dt><dd>{source.duration}</dd></div>
          <div><dt>Trạng thái</dt><dd>Sẵn sàng</dd></div>
        </dl>
      </div>
    </section>
  )
}

export function EngineCards({ engines }: { engines: EngineStatus[] }) {
  return (
    <section aria-labelledby="engines-title">
      <div className="section-heading compact-heading">
        <div>
          <span className="eyebrow">XỬ LÝ SONG SONG</span>
          <h2 id="engines-title">Trạng thái bộ máy</h2>
        </div>
      </div>
      <div className="engine-grid">
        {engines.map((engine) => (
          <article className={`panel engine-card ${engine.status}`} key={engine.id}>
            <VideoPreview variant={engine.id} label={`Xem trước ${engine.name}`} />
            <div className="engine-card-body">
              <div className="engine-title-row">
                <h3>{engine.name}</h3>
                <span className={`status-pill ${engine.status}`}>{statusLabels[engine.status]}</span>
              </div>
              <dl className="engine-stats">
                <div><dt>Thời gian</dt><dd>{engine.elapsedSeconds ? `${engine.elapsedSeconds} giây` : '—'}</dd></div>
                {engine.proxySavings && <div><dt>Tiết kiệm proxy</dt><dd>{engine.proxySavings}</dd></div>}
                <div><dt>Đầu ra</dt><dd>{engine.status === 'completed' ? engine.outputFilename : 'Đang chờ'}</dd></div>
              </dl>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

export function FinalOutput({ output, onOpenFolder, onReset }: {
  output: OutputMetadata
  onOpenFolder: () => void
  onReset: () => void
}) {
  return (
    <section className="panel final-panel" aria-labelledby="output-title">
      <div className="success-banner"><span>✓</span> Video đã hoàn tất</div>
      <div className="final-grid">
        <VideoPreview variant="final" label="Xem trước video cuối" />
        <div className="final-details">
          <span className="eyebrow">VIDEO ĐẦU RA</span>
          <h2 id="output-title">{output.filename}</h2>
          <dl className="output-metadata">
            <div><dt>Độ phân giải</dt><dd>{output.resolution}</dd></div>
            <div><dt>Thời lượng</dt><dd>{output.duration}</dd></div>
            <div><dt>Dung lượng</dt><dd>{output.fileSize}</dd></div>
          </dl>
          <div className="button-row">
            <button className="secondary-button" onClick={onOpenFolder}>Mở thư mục đầu ra</button>
            <button className="primary-button" onClick={onReset}>Tạo video khác</button>
          </div>
        </div>
      </div>
    </section>
  )
}
