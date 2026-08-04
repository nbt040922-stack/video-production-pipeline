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
})