export function VideoPreview({ variant = 'source', label, src, videoSrc }: {
  variant?: 'source' | 'hook' | 'review' | 'final'
  label: string
  src?: string
  videoSrc?: string
}) {
  return (
    <div
      className={`video-preview ${variant} ${src ? 'has-image' : ''} ${videoSrc ? 'has-video' : ''}`}
      role={videoSrc ? undefined : 'img'}
      aria-label={videoSrc ? undefined : label}
    >
      {videoSrc ? (
        <video className="preview-video" src={videoSrc} aria-label={label} controls preload="metadata" />
      ) : src ? (
        <img className="preview-image" src={src} alt="" />
      ) : (
        <div className="preview-scene">
          <span className="street-line one" />
          <span className="street-line two" />
          <span className="subject-silhouette" />
        </div>
      )}
      <div className="camera-tag">BODYCAM</div>
      {!videoSrc && <div className="preview-play" aria-hidden="true" />}
      {!videoSrc && <div className="preview-timecode">00:04:18</div>}
    </div>
  )
}
