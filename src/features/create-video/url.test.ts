import { describe, expect, it } from 'vitest'
import { isValidYouTubeUrl } from './url'

describe('isValidYouTubeUrl', () => {
  it.each([
    'https://www.youtube.com/watch?v=abc123',
    'https://youtu.be/abc123',
    'https://youtube.com/shorts/abc123',
  ])('accepts %s', (url) => expect(isValidYouTubeUrl(url)).toBe(true))

  it.each(['', 'hello', 'https://example.com/watch?v=abc', 'ftp://youtu.be/abc', 'https://youtu.be/abc?list=PL123'])('rejects %s', (url) => {
    expect(isValidYouTubeUrl(url)).toBe(false)
  })
})
