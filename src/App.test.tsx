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
    openOutputFolder: vi.fn().mockResolvedValue(undefined),
  }
}

async function start(client: PipelineClient) {
  render(<App client={client} />)
  fireEvent.change(screen.getByLabelText('Liên kết YouTube'), { target: { value: 'https://youtu.be/demo' } })
  fireEvent.click(screen.getByRole('button', { name: 'Tạo video' }))
}

describe('App', () => {
  it('shows initial idle state and validates bad URLs', () => {
    render(<App client={stubClient(makeJob('completed'))} />)
    expect(screen.getByRole('heading', { name: 'Tạo Bodycam Review' })).toBeInTheDocument()
    expect(screen.queryByText('Quy trình sản xuất')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Liên kết YouTube'), { target: { value: 'not-a-url' } })
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
    fireEvent.click(screen.getByRole('button', { name: 'Mở thư mục đầu ra' }))
    await waitFor(() => expect(client.openOutputFolder).toHaveBeenCalledWith('job-1'))
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
  })})
