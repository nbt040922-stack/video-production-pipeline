import type { CreateJobResult, CreateVideoInput, SourceMetadata, VideoJob } from '../types/job'

export interface PipelineClient {
  inspectSource(youtubeUrl: string): Promise<SourceMetadata>
  createJob(input: CreateVideoInput): Promise<CreateJobResult>
  getJob(jobId: string): Promise<VideoJob>
  cancelJob(jobId: string): Promise<void>
  retryJob(jobId: string): Promise<CreateJobResult>
}
