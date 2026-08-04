const youtubeHosts = new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'])

export function isValidYouTubeUrl(value: string): boolean {
  try {
    const url = new URL(value.trim())
    if (!['http:', 'https:'].includes(url.protocol) || !youtubeHosts.has(url.hostname)) return false
    if (url.searchParams.has('list')) return false
    if (url.hostname === 'youtu.be') return url.pathname.length > 1
    return Boolean(url.searchParams.get('v') || /^\/(shorts|live)\/[^/]+/.test(url.pathname))
  } catch {
    return false
  }
}
