import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendPipelineClient } from './backend-pipeline-client'

const backendJob = {
  job_id: 'job-1',
  youtube_url: 'https://youtu.be/demo',
  status: 'processing',
  elapsed_seconds: 8,
  stages: [{
    id: 'download',
    name: 'Tải video nguồn',
    status: 'running',
    elapsed_seconds: 2,
    message: 'Đang tải nguồn: 65%',
  }],
  source: null,
  hook_engine: { status: 'completed', progress: 100, message: 'Hook hoàn tất', elapsed_seconds: 8, output_filename: 'final_hook.mp4', preview_url: '/api/jobs/job-1/assets/hook' },
  review_engine: { status: 'pending', progress: 0, message: 'Đang chờ', elapsed_seconds: 0, output_filename: 'review.mp4' },
  output: null,
  error: null,
}

function response(body: unknown, ok = true) {
  return { ok, json: vi.fn().mockResolvedValue(body) } as unknown as Response
}

describe('BackendPipelineClient', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('creates a backend job', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(backendJob))
    vi.stubGlobal('fetch', fetchMock)

    const result = await new BackendPipelineClient('http://api').createJob({ youtubeUrl: backendJob.youtube_url })

    expect(result).toEqual({ jobId: 'job-1' })
    expect(fetchMock).toHaveBeenCalledWith('http://api/api/jobs', expect.objectContaining({ method: 'POST' }))
  })

  it('maps backend polling data into the UI model', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(backendJob)))
    const job = await new BackendPipelineClient('http://api').getJob('job-1')

    expect(job.status).toBe('processing')
    expect(job.stages[0]).toMatchObject({ status: 'running', elapsedSeconds: 2 })
    expect(job.engines.map((engine) => engine.name)).toEqual(['Hook Engine', 'Review Engine'])
    expect(job.engines[0]).toMatchObject({ progress: 100, message: 'Hook hoàn tất', previewUrl: 'http://api/api/jobs/job-1/assets/hook' })
  })

  it('sends cancellation, retry, login, and logout with cookies', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(backendJob))
      .mockResolvedValueOnce(response(backendJob))
      .mockResolvedValueOnce(response({ user: { id: 'u1', username: 'tester', display_name: 'Tester', role: 'user' } }))
      .mockResolvedValueOnce(response({ authenticated: false }))
    vi.stubGlobal('fetch', fetchMock)
    const client = new BackendPipelineClient('http://api')

    await client.cancelJob('job-1')
    await client.retryJob('job-1')
    await client.login('tester', 'secret')
    await client.logout()

    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://api/api/jobs/job-1/cancel', expect.objectContaining({ method: 'POST', credentials: 'include' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://api/api/jobs/job-1/retry', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(3, 'http://api/api/auth/login', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(4, 'http://api/api/auth/logout', expect.objectContaining({ method: 'POST' }))
  })

  it('returns structured backend errors to UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { message: 'Xử lý thất bại' } }, false)))
    await expect(new BackendPipelineClient('http://api').getJob('job-1')).rejects.toThrow('Xử lý thất bại')
  })

  it('changes the current user password', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ user: {} }))
    vi.stubGlobal('fetch', fetchMock)
    await new BackendPipelineClient('http://api').changePassword('old-password', 'new-password')
    expect(fetchMock).toHaveBeenCalledWith('http://api/api/auth/change-password', expect.objectContaining({
      method: 'POST', credentials: 'include',
      body: JSON.stringify({ current_password: 'old-password', new_password: 'new-password' }),
    }))
  })

  it('maps real source metadata and thumbnail URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...backendJob,
      source: {
        title: 'Real title',
        channel: 'Real channel',
        duration: '1:02',
        status: 'ready',
        thumbnail_url: '/api/jobs/job-1/assets/thumbnail',
      },
    })))
    const job = await new BackendPipelineClient('http://api').getJob('job-1')

    expect(job.source).toMatchObject({
      title: 'Real title',
      channel: 'Real channel',
      duration: '1:02',
      thumbnailUrl: 'http://api/api/jobs/job-1/assets/thumbnail',
    })
  })

  it('maps the final preview URL', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      ...backendJob,
      status: 'completed',
      output: {
        filename: 'final_video.mp4', resolution: '1920×1080', duration: '0:48', file_size: '16.7 MB',
        preview_url: '/api/jobs/job-1/assets/final',
      },
    })))
    const job = await new BackendPipelineClient('http://api').getJob('job-1')
    expect(job.output?.previewUrl).toBe('http://api/api/jobs/job-1/assets/final')
  })
})
