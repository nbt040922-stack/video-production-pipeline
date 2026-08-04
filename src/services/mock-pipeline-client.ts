import type { PipelineClient } from './pipeline-client'
import type {
  CreateJobResult,
  CreateVideoInput,
  EngineState,
  JobStage,
  SourceMetadata,
  VideoJob,
} from '../types/job'

export const MOCK_FAILURE_URL = 'https://youtu.be/mock-video?fixture=fail'

const stageDefinitions = [
  ['download', 'Tải video nguồn', 'Nhận video và kiểm tra dữ liệu đầu vào'],
  ['thumbnail', 'Chuẩn bị ảnh bìa', 'Tạo khung hình đại diện cho video'],
  ['hook', 'Tạo đoạn mở đầu', 'Chuẩn bị phần mở đầu thu hút'],
  ['script', 'Viết bài đánh giá', 'Soạn nội dung đánh giá video'],
  ['voice', 'Tạo giọng đọc', 'Chuyển nội dung thành giọng đọc'],
  ['footage', 'Chọn cảnh quay', 'Ghép cảnh phù hợp với nội dung'],
  ['review', 'Dựng video đánh giá', 'Kết xuất phần đánh giá hoàn chỉnh'],
  ['compose', 'Ghép video cuối', 'Kết hợp mở đầu và phần đánh giá'],
  ['validate', 'Kiểm tra đầu ra', 'Xác nhận chất lượng và thông số video'],
] as const

const source: SourceMetadata = {
  title: 'Bodycam Footage Review — Downtown Incident',
  channel: 'Public Safety Archive',
  duration: '12:48',
  status: 'ready',
}

export class MockPipelineClient implements PipelineClient {
  private jobs = new Map<string, VideoJob>()
  private timers = new Map<string, ReturnType<typeof setInterval>>()

  constructor(private readonly tickMs = 700) {}

  async inspectSource(): Promise<SourceMetadata> {
    return { ...source }
  }

  async createJob(input: CreateVideoInput): Promise<CreateJobResult> {
    const id = `mock-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
    const stages: JobStage[] = stageDefinitions.map(([stageId, name, description], index) => ({
      id: stageId,
      name,
      description,
      status: 'pending',
      elapsedSeconds: 0,
    }))
    const job: VideoJob = {
      id,
      sourceUrl: input.youtubeUrl,
      source: { ...source },
      status: 'validating',
      elapsedSeconds: 0,
      stages,
      engines: [
        { id: 'hook', name: 'Hook Engine', status: 'pending', elapsedSeconds: 0, outputFilename: 'final_hook.mp4' },
        { id: 'review', name: 'Review Engine', status: 'pending', elapsedSeconds: 0, outputFilename: 'review.mp4', proxySavings: 'Đang tính' },
      ],
    }
    this.jobs.set(id, job)
    this.timers.set(id, setInterval(() => this.advance(id), this.tickMs))
    return { jobId: id }
  }

  async getJob(jobId: string): Promise<VideoJob> {
    const job = this.jobs.get(jobId)
    if (!job) throw new Error('Không tìm thấy công việc')
    return structuredClone(job)
  }

  async cancelJob(jobId: string): Promise<void> {
    const job = this.requireJob(jobId)
    this.stop(jobId)
    job.status = 'cancelled'
    job.error = 'Đã hủy theo yêu cầu'
    job.stages.forEach((stage) => {
      if (stage.status === 'pending' || stage.status === 'running') stage.status = 'skipped'
    })
    job.engines.forEach((engine) => {
      if (engine.status === 'pending' || engine.status === 'running') engine.status = 'skipped'
    })
  }

  private advance(jobId: string): void {
    const job = this.requireJob(jobId)
    if (job.status === 'validating') {
      job.status = 'processing'
      job.stages[0].status = 'running'
      return
    }
    const currentIndex = job.stages.findIndex((stage) => stage.status === 'running')
    if (currentIndex < 0) return

    job.elapsedSeconds += 4
    job.stages[currentIndex].elapsedSeconds += 4

    if (job.sourceUrl === MOCK_FAILURE_URL && currentIndex === 3) {
      job.stages[currentIndex].status = 'failed'
      job.status = 'failed'
      job.error = 'Mô phỏng lỗi khi viết bài đánh giá'
      this.setEngine(job, 'review', 'failed')
      this.stop(jobId)
      return
    }

    job.stages[currentIndex].status = 'completed'
    this.updateEngines(job, currentIndex)

    if (currentIndex === job.stages.length - 1) {
      job.status = 'completed'
      job.output = {
        filename: 'final_video.mp4',
        resolution: '1920×1080',
        duration: '13:02',
        fileSize: '284 MB',
      }
      this.stop(jobId)
      return
    }

    job.stages[currentIndex + 1].status = 'running'
  }

  private updateEngines(job: VideoJob, stageIndex: number): void {
    if (stageIndex === 1) this.setEngine(job, 'hook', 'running')
    if (stageIndex === 2) this.setEngine(job, 'review', 'running')
    if (stageIndex === 4) this.setEngine(job, 'hook', 'completed')
    if (stageIndex === 6) this.setEngine(job, 'review', 'completed')
    job.engines.forEach((engine) => {
      if (engine.status === 'running') engine.elapsedSeconds += 4
    })
  }

  private setEngine(job: VideoJob, id: 'hook' | 'review', status: EngineState): void {
    const engine = job.engines.find((item) => item.id === id)
    if (engine) engine.status = status
  }

  private requireJob(jobId: string): VideoJob {
    const job = this.jobs.get(jobId)
    if (!job) throw new Error('Không tìm thấy công việc')
    return job
  }

  private stop(jobId: string): void {
    clearInterval(this.timers.get(jobId))
    this.timers.delete(jobId)
  }
}
