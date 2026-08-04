import type { PipelineClient } from './pipeline-client'
import type {
  CreateJobResult,
  CreateVideoInput,
  EngineState,
  JobStatus,
  SourceMetadata,
  StageStatus,
  VideoJob,
} from '../types/job'

interface BackendError {
  error?: { message?: string }
}

interface BackendStage {
  id: string
  name: string
  status: StageStatus | 'cancelled'
  elapsed_seconds: number
  message: string
}

interface BackendSource {
  title: string
  channel: string
  duration: string
  status: 'ready'
  thumbnail_url?: string | null
}
interface BackendJob {
  job_id: string
  youtube_url: string
  status: string
  elapsed_seconds: number
  stages: BackendStage[]
  source: BackendSource | null
  hook_engine: {
    status: EngineState | 'cancelled'
    elapsed_seconds: number
    output_filename: string
  }
  review_engine: {
    status: EngineState | 'cancelled'
    elapsed_seconds: number
    output_filename: string
    proxy_savings?: string
  }
  output: null | {
    filename: string
    resolution: string
    duration: string
    file_size: string
  }
  error?: { message: string } | null
}

const pendingSource: SourceMetadata = {
  title: 'Nguồn YouTube đang chờ xử lý',
  channel: 'Local backend',
  duration: 'Đang xác định',
  status: 'ready',
}

export class BackendPipelineClient implements PipelineClient {
  constructor(private readonly baseUrl = 'http://127.0.0.1:8000') {}

  async inspectSource(): Promise<SourceMetadata> {
    return pendingSource
  }

  async createJob(input: CreateVideoInput): Promise<CreateJobResult> {
    const job = await this.request<BackendJob>('/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ youtube_url: input.youtubeUrl }),
    })
    return { jobId: job.job_id }
  }

  async getJob(jobId: string): Promise<VideoJob> {
    return this.mapJob(await this.request<BackendJob>(`/api/jobs/${jobId}`))
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.request(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
  }

  async retryJob(jobId: string): Promise<CreateJobResult> {
    const job = await this.request<BackendJob>(`/api/jobs/${jobId}/retry`, { method: 'POST' })
    return { jobId: job.job_id }
  }

  private async request<T = unknown>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...init?.headers },
      })
    } catch {
      throw new Error('Không thể kết nối backend local.')
    }
    const payload = await response.json() as T & BackendError
    if (!response.ok) throw new Error(payload.error?.message ?? 'Backend trả về lỗi.')
    return payload
  }

  private mapJob(job: BackendJob): VideoJob {
    return {
      id: job.job_id,
      sourceUrl: job.youtube_url,
      source: job.source ? this.mapSource(job.source) : pendingSource,
      status: this.mapJobStatus(job.status),
      elapsedSeconds: job.elapsed_seconds,
      error: job.error?.message,
      stages: job.stages.map((stage) => ({
        id: stage.id,
        name: stage.name,
        description: stage.message,
        status: stage.status === 'cancelled' ? 'skipped' : stage.status,
        elapsedSeconds: stage.elapsed_seconds,
      })),
      engines: [
        {
          id: 'hook',
          name: 'Hook Engine',
          status: job.hook_engine.status === 'cancelled' ? 'skipped' : job.hook_engine.status,
          elapsedSeconds: job.hook_engine.elapsed_seconds,
          outputFilename: job.hook_engine.output_filename,
        },
        {
          id: 'review',
          name: 'Review Engine',
          status: job.review_engine.status === 'cancelled' ? 'skipped' : job.review_engine.status,
          elapsedSeconds: job.review_engine.elapsed_seconds,
          outputFilename: job.review_engine.output_filename,
          proxySavings: job.review_engine.proxy_savings,
        },
      ],
      output: job.output ? {
        filename: job.output.filename,
        resolution: job.output.resolution,
        duration: job.output.duration,
        fileSize: job.output.file_size,
      } : undefined,
    }
  }

  private mapSource(source: BackendSource): SourceMetadata {
    return {
      title: source.title,
      channel: source.channel,
      duration: source.duration,
      status: source.status,
      thumbnailUrl: source.thumbnail_url ? `${this.baseUrl}${source.thumbnail_url}` : undefined,
    }
  }
  private mapJobStatus(status: string): JobStatus {
    if (status === 'completed' || status === 'failed' || status === 'cancelled') return status
    if (status === 'queued' || status === 'validating') return 'validating'
    return 'processing'
  }
}
