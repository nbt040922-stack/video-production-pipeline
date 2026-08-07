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
  fallbackUsed?: boolean
  fallbackReason?: string
  outputDurationSeconds?: number
}

export interface OutputMetadata {
  filename: string
  resolution: string
  duration: string
  fileSize: string
  previewUrl?: string
  downloadUrl?: string
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
  queuePosition?: number
}

export interface SharedJobSummary {
  jobId: string
  sourceTitle?: string
  submittedAt: string
  status: string
  progress: number
  queuePosition?: number
  currentStage?: string
  finalOutputAvailable: boolean
  downloadUrl?: string
  error?: string
  ownerUsername?: string
}

export interface CurrentUser {
  id: string
  username: string
  displayName: string
  role: 'user' | 'admin'
}

export interface Readiness {
  status: 'ready' | 'degraded'
  checks: Record<string, boolean>
  freeDiskGb: number
  minimumFreeDiskGb: number
}
