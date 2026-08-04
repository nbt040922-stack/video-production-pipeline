import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SourcePreview } from './JobPanels'

describe('SourcePreview', () => {
  it('renders real backend metadata and thumbnail', () => {
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
})
