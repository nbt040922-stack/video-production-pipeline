import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EngineCards, SourcePreview } from './JobPanels'

describe('Job panels', () => {
  it('renders real backend source metadata and thumbnail', () => {
    const { container } = render(<SourcePreview source={{
      title: 'Real YouTube title',
      channel: 'Real channel',
      duration: '1:02',
      status: 'ready',
      thumbnailUrl: 'http://127.0.0.1:8000/api/jobs/job-1/assets/thumbnail',
    }} />)

    expect(screen.getByText('Real YouTube title')).toBeInTheDocument()
    expect(screen.getByText('Real channel')).toBeInTheDocument()
    expect(screen.getByText('1:02')).toBeInTheDocument()
    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      'http://127.0.0.1:8000/api/jobs/job-1/assets/thumbnail',
    )
  })

  it('shows real Hook progress and completed video preview', () => {
    const { rerender } = render(<EngineCards engines={[
      {
        id: 'hook', name: 'Hook Engine', status: 'running', progress: 25,
        message: 'Hook Engine đang tạo video: 12 giây', elapsedSeconds: 12,
        outputFilename: 'final_hook.mp4',
      },
    ]} />)

    expect(screen.getByText('Hook Engine đang tạo video: 12 giây · 25%')).toBeInTheDocument()

    rerender(<EngineCards engines={[
      {
        id: 'hook', name: 'Hook Engine', status: 'completed', progress: 100,
        message: 'Hook hoàn tất', elapsedSeconds: 80, outputFilename: 'final_hook.mp4',
        previewUrl: 'http://api/api/jobs/job-1/assets/hook',
      },
    ]} />)
    expect(screen.getByLabelText('Xem trước Hook Engine')).toHaveAttribute(
      'src', 'http://api/api/jobs/job-1/assets/hook',
    )
  })

  it('shows real Review progress, proxy result, fallback, and preview', () => {
    const { rerender } = render(<EngineCards engines={[
      {
        id: 'review', name: 'Review Engine', status: 'running', progress: 54,
        message: 'Đang chọn cảnh', elapsedSeconds: 30, outputFilename: 'review.mp4',
      },
    ]} />)
    expect(screen.getByText('Đang chọn cảnh · 54%')).toBeInTheDocument()

    rerender(<EngineCards engines={[
      {
        id: 'review', name: 'Review Engine', status: 'completed', progress: 100,
        message: 'Review hoàn tất', elapsedSeconds: 90, outputFilename: 'review.mp4',
        previewUrl: 'http://api/api/jobs/job-1/assets/review', proxySavings: '50,4%',
        fallbackUsed: true, fallbackReason: 'full_source', outputDurationSeconds: 104.25,
      },
    ]} />)
    expect(screen.getByText('50,4%')).toBeInTheDocument()
    expect(screen.getByText('Đã dùng toàn bộ nguồn')).toBeInTheDocument()
    expect(screen.getByText('104.3 giây')).toBeInTheDocument()
    expect(screen.getByLabelText('Xem trước Review Engine')).toHaveAttribute(
      'src', 'http://api/api/jobs/job-1/assets/review',
    )
  })

  it('shows Review failure state', () => {
    render(<EngineCards engines={[
      {
        id: 'review', name: 'Review Engine', status: 'failed', progress: 20,
        message: 'Không thể viết kịch bản review.', elapsedSeconds: 4, outputFilename: 'review.mp4',
      },
    ]} />)
    expect(screen.getByText('Thất bại')).toBeInTheDocument()
    expect(screen.getByText('Không thể viết kịch bản review.')).toBeInTheDocument()
  })
})
