import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from './App'
import type { PipelineClient } from './services/pipeline-client'
import type { SourceMetadata, VideoJob } from './types/job'

const source: SourceMetadata = {
  title: 'Mock Bodycam Review',
  channel: 'Mock Channel',
  duration: '10:00',
  status: 'ready',
}

function makeJob(status: VideoJob['status']): VideoJob {
  return {
    id: 'job-1',
    sourceUrl: 'https://youtu.be/demo',
    source,
    status,
    elapsedSeconds: 36,
    error: status === 'failed' ? 'Mô phỏng lỗi' : undefined,
    stages: [{
      id: 'download',
      name: 'Tải video nguồn',
      description: 'Tải nguồn',
      status: status === 'failed' ? 'failed' : 'completed',
      elapsedSeconds: 4,
    }],
    engines: [
      { id: 'hook', name: 'Hook Engine', status: status === 'failed' ? 'failed' : 'completed', progress: 100, message: 'Hoàn tất', elapsedSeconds: 8, outputFilename: 'final_hook.mp4' },
      { id: 'review', name: 'Review Engine', status: status === 'failed' ? 'failed' : 'completed', progress: 100, message: 'Hoàn tất', elapsedSeconds: 12, outputFilename: 'review.mp4' },
    ],
    output: status === 'completed' ? {
      filename: 'final_video.mp4',
      resolution: '1920×1080',
      duration: '10:12',
      fileSize: '220 MB',
      previewUrl: 'http://api/api/jobs/job-1/assets/final',
      downloadUrl: 'http://api/api/jobs/job-1/assets/final/download',
    } : undefined,
  }
}

function stubClient(job: VideoJob): PipelineClient & { createJob: ReturnType<typeof vi.fn>; retryJob: ReturnType<typeof vi.fn> } {
  return {
    inspectSource: vi.fn().mockResolvedValue(source),
    createJob: vi.fn().mockResolvedValue({ jobId: job.id }),
    getJob: vi.fn().mockResolvedValue(job),
    cancelJob: vi.fn().mockResolvedValue(undefined),
    retryJob: vi.fn().mockResolvedValue({ jobId: job.id }),
    listJobs: vi.fn().mockResolvedValue([]),
    login: vi.fn().mockResolvedValue({ id: 'u1', username: 'tester', displayName: 'Tester', role: 'user' }),
    logout: vi.fn().mockResolvedValue(undefined),
    changePassword: vi.fn().mockResolvedValue(undefined),
    getCurrentUser: vi.fn().mockResolvedValue({ id: 'u1', username: 'tester', displayName: 'Tester', role: 'user' }),
    getReadiness: vi.fn().mockResolvedValue({ status: 'ready', checks: {}, freeDiskGb: 100, minimumFreeDiskGb: 30 }),
  }
}

async function start(client: PipelineClient) {
  render(<App client={client} />)
  fireEvent.change(await screen.findByLabelText('Liên kết YouTube'), { target: { value: 'https://youtu.be/demo' } })
  fireEvent.click(screen.getByRole('button', { name: 'Tạo video' }))
}

describe('App', () => {
  it('shows initial idle state and validates bad URLs', async () => {
    render(<App client={stubClient(makeJob('completed'))} />)
    expect(await screen.findByRole('heading', { name: 'Tạo Bodycam Review' })).toBeInTheDocument()
    expect(screen.queryByText('Quy trình sản xuất')).not.toBeInTheDocument()

    fireEvent.change(await screen.findByLabelText('Liên kết YouTube'), { target: { value: 'not-a-url' } })
    expect(screen.getByText(/URL không hợp lệ/)).toBeInTheDocument()
  })

  it('starts through PipelineClient and displays final output', async () => {
    const client = stubClient(makeJob('completed'))
    await start(client)

    await waitFor(() => expect(client.createJob).toHaveBeenCalledWith({ youtubeUrl: 'https://youtu.be/demo' }))
    expect(await screen.findByText('final_video.mp4')).toBeInTheDocument()
    expect(screen.getByText('1920×1080')).toBeInTheDocument()
    expect(screen.getByText('Hook Engine')).toBeInTheDocument()
    expect(screen.getByText('Review Engine')).toBeInTheDocument()
    expect(screen.getByLabelText('Xem trước video cuối')).toHaveAttribute('src', 'http://api/api/jobs/job-1/assets/final')
    expect(screen.getByRole('link', { name: 'Mở video' })).toHaveAttribute('href', 'http://api/api/jobs/job-1/assets/final')
    expect(screen.getAllByRole('link').length).toBeGreaterThan(0)
  })

  it('retries a failed job and resets', async () => {
    const client = stubClient(makeJob('failed'))
    await start(client)

    fireEvent.click(await screen.findByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(client.retryJob).toHaveBeenCalledWith('job-1'))
    fireEvent.click(screen.getByRole('button', { name: 'Đặt lại' }))
    expect(screen.getByLabelText('Liên kết YouTube')).toHaveValue('')
    expect(screen.queryByText('Mô phỏng lỗi')).not.toBeInTheDocument()
  })

  it('displays backend request errors', async () => {
    const client = stubClient(makeJob('completed'))
    client.createJob.mockRejectedValue(new Error('Không thể kết nối backend local.'))
    await start(client)

    expect(await screen.findByRole('alert')).toHaveTextContent('Không thể kết nối backend local.')
  })

  it('shows login and authenticates with a user account', async () => {
    const client = stubClient(makeJob('completed'))
    vi.mocked(client.getCurrentUser).mockResolvedValue(null)
    render(<App client={client} />)
    fireEvent.change(await screen.findByLabelText(/T.n ..ng nh.p/), { target: { value: 'tester' } })
    const password = await screen.findByLabelText(/^M.t kh.u$/)
    fireEvent.change(password, { target: { value: 'internal-pass' } })
    fireEvent.click(screen.getByRole('button', { name: /..ng nh.p/ }))
    await waitFor(() => expect(client.login).toHaveBeenCalledWith('tester', 'internal-pass'))
    expect(await screen.findByRole('heading', { name: /T.o Bodycam Review/ })).toBeInTheDocument()
  })

  it('shows shared queue position and final download', async () => {
    const client = stubClient(makeJob('completed'))
    vi.mocked(client.getCurrentUser).mockResolvedValue({ id: 'admin', username: 'admin', displayName: 'Quản trị', role: 'admin' })
    vi.mocked(client.listJobs).mockResolvedValue([{
      jobId: 'job-2', sourceTitle: 'Shared LAN job', submittedAt: '2026-08-05T00:00:00Z',
      status: 'queued', progress: 0, queuePosition: 2, finalOutputAvailable: true,
      downloadUrl: '/api/jobs/job-2/assets/final/download',
      ownerUsername: 'alice',
    }])
    render(<App client={client} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Tất cả công việc' }))
    expect(await screen.findByText('Shared LAN job')).toBeInTheDocument()
    expect(screen.getByText(/#2/)).toBeInTheDocument()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /T.i video/ })).toHaveAttribute('href', '/api/jobs/job-2/assets/final/download')
  })

  it('shows server unavailable state', async () => {
    const client = stubClient(makeJob('completed'))
    vi.mocked(client.getCurrentUser).mockRejectedValue(new Error('offline'))
    render(<App client={client} />)
    expect(await screen.findByRole('heading', { name: /M.y ch. ch.a s.n s.ng/ })).toBeInTheDocument()
  })

  it('logs out to the login screen', async () => {
    const client = stubClient(makeJob('completed'))
    render(<App client={client} />)
    fireEvent.click(await screen.findByRole('button', { name: /..ng xu.t/ }))
    await waitFor(() => expect(client.logout).toHaveBeenCalled())
    expect(await screen.findByLabelText(/^M.t kh.u$/)).toBeInTheDocument()
  })

  it('returns to login when the session expires', async () => {
    const client = stubClient(makeJob('completed'))
    vi.mocked(client.listJobs).mockRejectedValue(Object.assign(new Error('Cần đăng nhập.'), { name: 'AuthenticationRequiredError' }))
    render(<App client={client} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Công việc của tôi' }))
    expect(await screen.findByLabelText(/^M.t kh.u$/)).toBeInTheDocument()
  })

  it('changes password from settings', async () => {
    const client = stubClient(makeJob('completed'))
    render(<App client={client} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Cài đặt' }))
    fireEvent.change(screen.getByLabelText('Mật khẩu hiện tại'), { target: { value: 'Matkhau-cu@16' } })
    fireEvent.change(screen.getByLabelText('Mật khẩu mới'), { target: { value: 'Matkhau-moi@16' } })
    fireEvent.change(screen.getByLabelText('Nhập lại mật khẩu mới'), { target: { value: 'Matkhau-moi@16' } })
    fireEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    await waitFor(() => expect(client.changePassword).toHaveBeenCalledWith('Matkhau-cu@16', 'Matkhau-moi@16'))
    expect(await screen.findByText('Đổi mật khẩu thành công.')).toBeInTheDocument()
  })

})
