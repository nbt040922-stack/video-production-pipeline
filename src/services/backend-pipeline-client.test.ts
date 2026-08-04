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
  hook_engine: { status: 'pending', elapsed_seconds: 0, output_filename: 'final_hook.mp4' },
  review_engine: { status: 'pending', elapsed_seconds: 0, output_filename: 'review.mp4' },
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
  })

  it('sends cancellation and retry to backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(backendJob))
    vi.stubGlobal('fetch', fetchMock)
    const client = new BackendPipelineClient('http://api')

    await client.cancelJob('job-1')
    await client.retryJob('job-1')

    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://api/api/jobs/job-1/cancel', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://api/api/jobs/job-1/retry', expect.objectContaining({ method: 'POST' }))
  })

  it('returns structured backend errors to UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({ error: { message: 'Xử lý thất bại' } }, false)))
    await expect(new BackendPipelineClient('http://api').getJob('job-1')).rejects.toThrow('Xử lý thất bại')
  })
})
