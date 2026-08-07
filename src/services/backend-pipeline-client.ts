import type { PipelineClient } from './pipeline-client'
import type {
  CreateJobResult,
  CurrentUser,
  CreateVideoInput,
  EngineState,
  JobStatus,
  Readiness,
  SharedJobSummary,
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
  queue_position?: number
  stages: BackendStage[]
  source: BackendSource | null
  hook_engine: {
    status: EngineState | 'cancelled'
    progress: number
    message: string
    elapsed_seconds: number
    output_filename: string
    preview_url?: string | null
  }
  review_engine: {
    status: EngineState | 'cancelled'
    progress: number
    message: string
    elapsed_seconds: number
    output_filename: string
    preview_url?: string | null
    proxy_savings?: string
    fallback_used?: boolean | null
    fallback_reason?: string | null
    output_duration_seconds?: number | null
  }
  output: null | {
    filename: string
    resolution: string
    duration: string
    file_size: string
    preview_url?: string | null
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
  constructor(private readonly baseUrl = '') {}

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

  async listJobs(): Promise<SharedJobSummary[]> {
    const jobs = await this.request<Array<{
      job_id: string
      source_title?: string
      submitted_at: string
      status: string
      progress: number
      queue_position?: number
      current_stage?: string
      final_output_available: boolean
      error?: string
      owner_username?: string
    }>>('/api/jobs')
    return jobs.map((job) => ({
      jobId: job.job_id,
      sourceTitle: job.source_title,
      submittedAt: job.submitted_at,
      status: job.status,
      progress: job.progress,
      queuePosition: job.queue_position,
      currentStage: job.current_stage,
      finalOutputAvailable: job.final_output_available,
      downloadUrl: job.final_output_available ? this.baseUrl + '/api/jobs/' + job.job_id + '/assets/final/download' : undefined,
      error: job.error,
      ownerUsername: job.owner_username,
    }))
  }

  async cancelJob(jobId: string): Promise<void> {
    await this.request(`/api/jobs/${jobId}/cancel`, { method: 'POST' })
  }

  async retryJob(jobId: string): Promise<CreateJobResult> {
    const job = await this.request<BackendJob>(`/api/jobs/${jobId}/retry`, { method: 'POST' })
    return { jobId: job.job_id }
  }

  async login(username: string, password: string): Promise<CurrentUser> {
    const response = await this.request<{ user: BackendUser }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    })
    return this.mapUser(response.user)
  }

  async logout(): Promise<void> {
    await this.request('/api/auth/logout', { method: 'POST' })
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    await this.request('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    })
  }

  async getCurrentUser(): Promise<CurrentUser | null> {
    const response = await this.request<{ authenticated: boolean; user: BackendUser | null }>('/api/auth/me')
    return response.authenticated && response.user ? this.mapUser(response.user) : null
  }

  async getReadiness(): Promise<Readiness> {
    const value = await this.request<{
      status: 'ready' | 'degraded'
      checks: Record<string, boolean>
      free_disk_gb: number
      minimum_free_disk_gb: number
    }>('/api/readiness')
    return {
      status: value.status,
      checks: value.checks,
      freeDiskGb: value.free_disk_gb,
      minimumFreeDiskGb: value.minimum_free_disk_gb,
    }
  }

  private async request<T = unknown>(path: string, init?: RequestInit): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...init?.headers },
      })
    } catch {
      throw new Error('Không thể kết nối backend local.')
    }
    const payload = await response.json() as T & BackendError
    if (!response.ok) {
      const error = new Error(payload.error?.message ?? 'Backend trả về lỗi.')
      if (response.status === 401) error.name = 'AuthenticationRequiredError'
      throw error
    }
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
      queuePosition: job.queue_position,
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
          progress: job.hook_engine.progress,
          message: job.hook_engine.message,
          elapsedSeconds: job.hook_engine.elapsed_seconds,
          outputFilename: job.hook_engine.output_filename,
          previewUrl: job.hook_engine.preview_url ? `${this.baseUrl}${job.hook_engine.preview_url}` : undefined,
        },
        {
          id: 'review',
          name: 'Review Engine',
          status: job.review_engine.status === 'cancelled' ? 'skipped' : job.review_engine.status,
          progress: job.review_engine.progress,
          message: job.review_engine.message,
          elapsedSeconds: job.review_engine.elapsed_seconds,
          outputFilename: job.review_engine.output_filename,
          previewUrl: job.review_engine.preview_url ? `${this.baseUrl}${job.review_engine.preview_url}` : undefined,
          proxySavings: job.review_engine.proxy_savings,
          fallbackUsed: job.review_engine.fallback_used ?? undefined,
          fallbackReason: job.review_engine.fallback_reason ?? undefined,
          outputDurationSeconds: job.review_engine.output_duration_seconds ?? undefined,
        },
      ],
      output: job.output ? {
        filename: job.output.filename,
        resolution: job.output.resolution,
        duration: job.output.duration,
        fileSize: job.output.file_size,
        downloadUrl: this.baseUrl + '/api/jobs/' + job.job_id + '/assets/final/download',
        previewUrl: job.output.preview_url ? `${this.baseUrl}${job.output.preview_url}` : undefined,
      } : undefined,
    }
  }

  private mapUser(user: BackendUser): CurrentUser {
    return { id: user.id, username: user.username, displayName: user.display_name, role: user.role }
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

interface BackendUser {
  id: string
  username: string
  display_name: string
  role: 'user' | 'admin'
}
