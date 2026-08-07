import { type FormEvent, useEffect, useState } from 'react'
import { AppShell, type Page } from './components/layout/AppShell'
import { EngineCards, FinalOutput, SourcePreview } from './components/jobs/JobPanels'
import { PipelineProgress } from './components/pipeline/PipelineProgress'
import { isValidYouTubeUrl } from './features/create-video/url'
import { useVideoJob } from './features/job-monitor/use-video-job'
import type { PipelineClient } from './services/pipeline-client'
import type { CurrentUser, Readiness, SharedJobSummary, SourceMetadata } from './types/job'

export function App({ client: pipelineClient }: { client: PipelineClient }) {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>()
  const [readiness, setReadiness] = useState<Readiness>()
  const [serverError, setServerError] = useState('')
  const [page, setPage] = useState<Page>('new')
  const [url, setUrl] = useState('')
  const [source, setSource] = useState<SourceMetadata>()
  const [notice, setNotice] = useState('')
  const [jobs, setJobs] = useState<SharedJobSummary[]>([])
  const { job, clientError, isStarting, start, cancel, retry, reset } = useVideoJob(pipelineClient)
  const validUrl = isValidYouTubeUrl(url)
  const busy = job?.status === 'validating' || job?.status === 'processing' || isStarting

  useEffect(() => {
    let active = true
    Promise.all([pipelineClient.getCurrentUser(), pipelineClient.getReadiness()])
      .then(([user, state]) => {
        if (!active) return
        setCurrentUser(user)
        setReadiness(state)
        setServerError('')
      })
      .catch(() => {
        if (active) setServerError('Không thể kết nối máy chủ Video Production Pipeline.')
      })
    return () => { active = false }
  }, [pipelineClient])

  useEffect(() => {
    if (!currentUser || page !== 'jobs') return
    let active = true
    const refresh = () => pipelineClient.listJobs()
      .then((items) => { if (active) setJobs(items) })
      .catch((reason) => {
        if (!active) return
        if (reason instanceof Error && reason.name === 'AuthenticationRequiredError') setCurrentUser(null)
        else setServerError('Không thể tải danh sách công việc.')
      })
    void refresh()
    const timer = setInterval(refresh, 2000)
    return () => { active = false; clearInterval(timer) }
  }, [currentUser, page, pipelineClient])

  useEffect(() => {
    let active = true
    setSource(undefined)
    if (!currentUser || !validUrl) return
    void pipelineClient.inspectSource(url).then((metadata) => {
      if (active) setSource(metadata)
    })
    return () => { active = false }
  }, [currentUser, pipelineClient, url, validUrl])

  if (serverError && currentUser === undefined) return <Unavailable message={serverError} />
  if (currentUser === undefined) return <Unavailable message="Đang kết nối máy chủ…" />
  if (!currentUser) {
    return <Login onLogin={async (username, password) => {
      setCurrentUser(await pipelineClient.login(username, password))
      setReadiness(await pipelineClient.getReadiness())
    }} />
  }

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

  const handleLogout = async () => {
    await pipelineClient.logout()
    setCurrentUser(null)
  }

  return (
    <AppShell
      page={page}
      onPageChange={setPage}
      busy={busy}
      degraded={readiness?.status === 'degraded'}
      onLogout={() => void handleLogout()}
      userName={currentUser.displayName}
      isAdmin={currentUser.role === 'admin'}
    >
      {readiness?.status === 'degraded' && (
        <div className="job-alert failed" role="alert">
          Máy chủ chưa sẵn sàng. Kiểm tra cấu hình engine, frontend build và dung lượng đĩa.
        </div>
      )}
      {serverError && <div className="job-alert failed" role="alert">{serverError}</div>}
      {page === 'jobs' ? (
        <SharedJobs jobs={jobs} isAdmin={currentUser.role === 'admin'} />
      ) : page === 'settings' ? (
        <PasswordSettings client={pipelineClient} />
      ) : page !== 'new' ? (
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
            </div>
            <label htmlFor="youtube-url">Liên kết YouTube</label>
            <div className={'url-control ' + (url && !validUrl ? 'invalid' : '')}>
              <span className="youtube-mark" aria-hidden="true">—</span>
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
            <div id="url-help" className={'field-message ' + (url && !validUrl ? 'error' : '')} role="status">
              {url && !validUrl
                ? 'URL không hợp lệ. Hãy dùng liên kết youtube.com hoặc youtu.be.'
                : notice || ' '}
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
              <div className={'job-alert ' + (job?.status ?? 'failed')} role="alert">{job?.error || clientError}</div>
            )}
            {job?.queuePosition && <div className="job-alert">Vị trí hàng đợi: {job.queuePosition}</div>}
          </section>

          {(source || job?.source) && <SourcePreview source={job?.source ?? source!} />}
          {job && <PipelineProgress stages={job.stages} />}
          {job && <EngineCards engines={job.engines} />}
          {job?.output && <FinalOutput output={job.output} onReset={handleReset} />}
        </div>
      )}
    </AppShell>
  )
}

function Login({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    try {
      await onLogin(username, password)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể đăng nhập.')
    }
  }
  return (
    <main className="login-page">
      <form className="panel login-card" onSubmit={(event) => void submit(event)}>
        <div className="brand-mark">VP</div>
        <h1>Video Production Pipeline</h1>
        <p>Đăng nhập bằng tài khoản riêng của bạn.</p>
        <label htmlFor="username">Tên đăng nhập</label>
        <input id="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} autoFocus />
        <label htmlFor="access-password">Mật khẩu</label>
        <input id="access-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} />
        {error && <div className="job-alert failed" role="alert">{error}</div>}
        <button className="primary-button" disabled={!username || !password}>Đăng nhập</button>
      </form>
    </main>
  )
}

function SharedJobs({ jobs, isAdmin }: { jobs: SharedJobSummary[]; isAdmin: boolean }) {
  return (
    <section className="panel shared-jobs" aria-labelledby="jobs-title">
      <h2 id="jobs-title">Hàng đợi và công việc gần đây</h2>
      {jobs.length === 0 ? <p>Chưa có công việc.</p> : (
        <div className="jobs-list">
          {jobs.map((job) => (
            <article className="shared-job-row" key={job.jobId}>
              <div><strong>{job.sourceTitle || 'Đang đọc nguồn YouTube'}</strong><small>{new Date(job.submittedAt).toLocaleString()}</small></div>
              {isAdmin && <span>{job.ownerUsername || 'legacy'}</span>}
              <span>{job.queuePosition ? 'Hàng đợi #' + job.queuePosition : job.currentStage || job.status}</span>
              <span>{job.progress}%</span>
              {job.downloadUrl ? <a className="secondary-button" href={job.downloadUrl}>Tải video</a> : <span>—</span>}
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function Unavailable({ message }: { message: string }) {
  return <main className="login-page"><section className="panel login-card"><h1>Máy chủ chưa sẵn sàng</h1><p>{message}</p></section></main>
}

function PasswordSettings({ client }: { client: PipelineClient }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (newPassword !== confirmPassword) {
      setMessage('Hai lần nhập mật khẩu mới không giống nhau.')
      return
    }
    setSaving(true)
    setMessage('')
    try {
      await client.changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage('Đổi mật khẩu thành công.')
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : 'Không thể đổi mật khẩu.')
    } finally {
      setSaving(false)
    }
  }
  return (
    <form className="panel password-settings" onSubmit={(event) => void submit(event)}>
      <h2>Đổi mật khẩu</h2>
      <p>Mật khẩu mới cần ít nhất 10 ký tự.</p>
      <label htmlFor="current-password">Mật khẩu hiện tại</label>
      <input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
      <label htmlFor="new-password">Mật khẩu mới</label>
      <input id="new-password" type="password" autoComplete="new-password" minLength={10} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
      <label htmlFor="confirm-password">Nhập lại mật khẩu mới</label>
      <input id="confirm-password" type="password" autoComplete="new-password" minLength={10} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
      {message && <div className={'job-alert ' + (message.includes('thành công') ? 'completed' : 'failed')} role="status">{message}</div>}
      <button className="primary-button" disabled={saving || !currentPassword || newPassword.length < 10 || !confirmPassword}>
        {saving ? 'Đang lưu…' : 'Đổi mật khẩu'}
      </button>
    </form>
  )
}

function PlaceholderPage({ page }: { page: Exclude<Page, 'new' | 'jobs' | 'settings'> }) {
  const copy = {
    outputs: ['Video đầu ra', 'Các video đã hoàn tất xuất hiện trong trang Công việc.'],
  }[page]
  return (
    <section className="panel placeholder-panel">
      <span className="placeholder-icon">—</span>
      <h2>{copy[0]}</h2>
      <p>{copy[1]}</p>
    </section>
  )
}
