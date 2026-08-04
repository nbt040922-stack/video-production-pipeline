import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MOCK_FAILURE_URL, MockPipelineClient } from './mock-pipeline-client'
import type { PipelineClient } from './pipeline-client'

describe('MockPipelineClient', () => {
  let client: MockPipelineClient

  beforeEach(() => {
    vi.useFakeTimers()
    client = new MockPipelineClient(100)
  })

  afterEach(() => vi.useRealTimers())

  it('implements PipelineClient and starts in validation', async () => {
    const contract: PipelineClient = client
    const { jobId } = await contract.createJob({ youtubeUrl: 'https://youtu.be/demo' })
    const job = await contract.getJob(jobId)

    expect(job.status).toBe('validating')
    expect(job.stages[0].status).toBe('pending')
  })

  it('advances stages and completes successfully', async () => {
    const { jobId } = await client.createJob({ youtubeUrl: 'https://youtu.be/demo' })
    vi.advanceTimersByTime(1000)
    const job = await client.getJob(jobId)

    expect(job.stages.every((stage) => stage.status === 'completed')).toBe(true)
    expect(job.status).toBe('completed')
    expect(job.output?.filename).toBe('final_video.mp4')
  })

  it('supports cancellation', async () => {
    const { jobId } = await client.createJob({ youtubeUrl: 'https://youtu.be/demo' })
    await client.cancelJob(jobId)
    const job = await client.getJob(jobId)

    expect(job.status).toBe('cancelled')
    expect(job.stages.every((stage) => ['completed', 'skipped'].includes(stage.status))).toBe(true)
  })

  it('supports deterministic failure fixture', async () => {
    const { jobId } = await client.createJob({ youtubeUrl: MOCK_FAILURE_URL })
    vi.advanceTimersByTime(500)
    const job = await client.getJob(jobId)

    expect(job.status).toBe('failed')
    expect(job.stages[3].status).toBe('failed')
  })
})
