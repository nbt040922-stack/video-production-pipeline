export function VideoPreview({ variant = 'source', label }: {
  variant?: 'source' | 'hook' | 'review' | 'final'
  label: string
}) {
  return (
    <div className={`video-preview ${variant}`} role="img" aria-label={label}>
      <div className="camera-tag">BODYCAM</div>
      <div className="preview-scene">
        <span className="street-line one" />
        <span className="street-line two" />
        <span className="subject-silhouette" />
      </div>
      <div className="preview-play" aria-hidden="true" />
      <div className="preview-timecode">00:04:18</div>
    </div>
  )
}
