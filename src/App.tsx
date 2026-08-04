import { useEffect, useMemo, useState } from 'react'
import { AppShell, type Page } from './components/layout/AppShell'
import { EngineCards, FinalOutput, SourcePreview } from './components/jobs/JobPanels'
import { PipelineProgress } from './components/pipeline/PipelineProgress'
import { isValidYouTubeUrl } from './features/create-video/url'
import { useVideoJob } from './features/job-monitor/use-video-job'
import { MockPipelineClient, MOCK_FAILURE_URL } from './services/mock-pipeline-client'
import type { PipelineClient } from './services/pipeline-client'
import type { SourceMetadata } from './types/job'

export function App({ client }: { client?: PipelineClient }) {
  const pipelineClient = useMemo(() => client ?? new MockPipelineClient(), [client])
  const [page, setPage] = useState<Page>('new')
  const [url, setUrl] = useState('')
  const [source, setSource] = useState<SourceMetadata>()
  const [notice, setNotice] = useState('')
  const { job, clientError, isStarting, start, cancel, retry, reset } = useVideoJob(pipelineClient)
  const validUrl = isValidYouTubeUrl(url)
  const busy = job?.status === 'validating' || job?.status === 'processing' || isStarting

  useEffect(() => {
    let active = true
    setSource(undefined)
    if (!validUrl) return
    void pipelineClient.inspectSource(url).then((metadata) => {
      if (active) setSource(metadata)
    })
    return () => { active = false }
  }, [pipelineClient, url, validUrl])

  const handlePaste = async () => {
    try {
      setUrl(await navigator.clipboard.readText())
      setNotice('')
    } catch {
      setNotice('Không thể đọc clipboard. Hãy dán URL bằng Ctrl+V.')
    }
  }

  const handleStart = async () => {
    if (!validUrl || busy) return
    setNotice('')
    await start(url)
  }

  const handleReset = () => {
    reset()
    setUrl('')
    setSource(undefined)
    setNotice('')
  }

  return (
    <AppShell page={page} onPageChange={setPage} busy={busy}>
      {page !== 'new' ? (
        <PlaceholderPage page={page} />
      ) : (
        <div className="content-grid">
          <section className="panel create-card" aria-labelledby="create-title">
            <div className="section-heading">
              <div>
                <span className="eyebrow">VIDEO MỚI</span>
                <h2 id="create-title">Tạo Bodycam Review</h2>
                <p>Dán liên kết YouTube. Hệ thống sẽ xử lý phần còn lại.</p>
              </div>
              <span className="mock-badge">CHẾ ĐỘ MÔ PHỎNG</span>
            </div>
            <label htmlFor="youtube-url">Liên kết YouTube</label>
            <div className={`url-control ${url && !validUrl ? 'invalid' : ''}`}>
              <span className="youtube-mark" aria-hidden="true">▶</span>
              <input
                id="youtube-url"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=..."
                disabled={busy}
                aria-invalid={Boolean(url && !validUrl)}
                aria-describedby="url-help"
              />
              <button className="paste-button" onClick={handlePaste} disabled={busy}>Dán</button>
            </div>
            <div id="url-help" className={`field-message ${url && !validUrl ? 'error' : ''}`} role="status">
              {url && !validUrl
                ? 'URL không hợp lệ. Hãy dùng liên kết youtube.com hoặc youtu.be.'
                : notice || (import.meta.env.DEV ? `Fixture lỗi: ${MOCK_FAILURE_URL}` : ' ')}
            </div>
            <div className="create-actions">
              <button className="primary-button generate-button" onClick={handleStart} disabled={!validUrl || busy}>
                {busy ? <><span className="spinner" /> Đang tạo video</> : 'Tạo video'}
              </button>
              {busy && <button className="danger-button" onClick={() => void cancel()}>Hủy công việc</button>}
              {(job?.status === 'failed' || job?.status === 'cancelled') && (
                <button className="primary-button" onClick={() => void retry()}>Thử lại</button>
              )}
              {job && !busy && <button className="ghost-button" onClick={handleReset}>Đặt lại</button>}
            </div>
            {(job?.error || clientError) && (
              <div className={`job-alert ${job?.status ?? 'failed'}`} role="alert">{job?.error || clientError}</div>
            )}
          </section>

          {(source || job?.source) && <SourcePreview source={job?.source ?? source!} />}
          {job && <PipelineProgress stages={job.stages} />}
          {job && <EngineCards engines={job.engines} />}
          {job?.output && (
            <FinalOutput
              output={job.output}
              onOpenFolder={() => setNotice('Mở thư mục sẽ hoạt động khi đóng gói ứng dụng desktop.')}
              onReset={handleReset}
            />
          )}
        </div>
      )}
    </AppShell>
  )
}

function PlaceholderPage({ page }: { page: Exclude<Page, 'new'> }) {
  const copy = {
    jobs: ['Công việc', 'Lịch sử công việc sẽ xuất hiện tại đây.'],
    outputs: ['Video đầu ra', 'Các video đã hoàn tất sẽ xuất hiện tại đây.'],
    settings: ['Cài đặt', 'Cài đặt ứng dụng sẽ được bổ sung khi kết nối backend.'],
  }[page]
  return (
    <section className="panel placeholder-panel">
      <span className="placeholder-icon">□</span>
      <h2>{copy[0]}</h2>
      <p>{copy[1]}</p>
    </section>
  )
}
