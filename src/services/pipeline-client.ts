import type {
  CreateJobResult,
  CurrentUser,
  CreateVideoInput,
  Readiness,
  SharedJobSummary,
  SourceMetadata,
  VideoJob,
} from '../types/job'

export interface PipelineClient {
  inspectSource(youtubeUrl: string): Promise<SourceMetadata>
  createJob(input: CreateVideoInput): Promise<CreateJobResult>
  getJob(jobId: string): Promise<VideoJob>
  listJobs(): Promise<SharedJobSummary[]>
  cancelJob(jobId: string): Promise<void>
  retryJob(jobId: string): Promise<CreateJobResult>
  login(username: string, password: string): Promise<CurrentUser>
  logout(): Promise<void>
  changePassword(currentPassword: string, newPassword: string): Promise<void>
  getCurrentUser(): Promise<CurrentUser | null>
  getReadiness(): Promise<Readiness>
}
