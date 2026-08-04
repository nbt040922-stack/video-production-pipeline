export function VideoPreview({ variant = 'source', label, src }: {
  variant?: 'source' | 'hook' | 'review' | 'final'
  label: string
  src?: string
}) {
  return (
    <div className={`video-preview ${variant} ${src ? 'has-image' : ''}`} role="img" aria-label={label}>
      {src ? (
        <img className="preview-image" src={src} alt="" />
      ) : (
        <div className="preview-scene">
          <span className="street-line one" />
          <span className="street-line two" />
          <span className="subject-silhouette" />
        </div>
      )}
      <div className="camera-tag">BODYCAM</div>
      <div className="preview-play" aria-hidden="true" />
      <div className="preview-timecode">00:04:18</div>
    </div>
  )
}
