export type JobStatus =
  | 'validating'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type StageStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export type EngineState = 'pending' | 'running' | 'completed' | 'failed' | 'skipped'

export interface CreateVideoInput {
  youtubeUrl: string
}

export interface CreateJobResult {
  jobId: string
}

export interface SourceMetadata {
  title: string
  channel: string
  duration: string
  thumbnailUrl?: string
  status: 'ready'
}

export interface JobStage {
  id: string
  name: string
  description: string
  status: StageStatus
  elapsedSeconds: number
}

export interface EngineStatus {
  id: 'hook' | 'review'
  name: string
  status: EngineState
  progress: number
  message: string
  elapsedSeconds: number
  outputFilename: string
  previewUrl?: string
  proxySavings?: string
}

export interface OutputMetadata {
  filename: string
  resolution: string
  duration: string
  fileSize: string
}

export interface VideoJob {
  id: string
  sourceUrl: string
  source: SourceMetadata
  status: JobStatus
  elapsedSeconds: number
  stages: JobStage[]
  engines: EngineStatus[]
  output?: OutputMetadata
  error?: string
}
