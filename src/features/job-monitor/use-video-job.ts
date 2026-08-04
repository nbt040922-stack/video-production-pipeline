import { useCallback, useEffect, useState } from 'react'
import type { PipelineClient } from '../../services/pipeline-client'
import type { VideoJob } from '../../types/job'

const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])
const messageOf = (error: unknown, fallback: string) => error instanceof Error ? error.message : fallback

export function useVideoJob(client: PipelineClient) {
  const [job, setJob] = useState<VideoJob>()
  const [jobId, setJobId] = useState<string>()
  const [isStarting, setIsStarting] = useState(false)
  const [clientError, setClientError] = useState('')

  useEffect(() => {
    if (!jobId) return
    let active = true
    let timer: ReturnType<typeof setInterval>

    const refresh = async () => {
      try {
        const next = await client.getJob(jobId)
        if (!active) return
        setJob(next)
        setClientError('')
        if (terminalStatuses.has(next.status)) clearInterval(timer)
      } catch (error) {
        if (active) setClientError(messageOf(error, 'Không thể đọc trạng thái công việc.'))
        clearInterval(timer)
      }
    }

    void refresh()
    timer = setInterval(() => void refresh(), 120)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [client, jobId])

  const start = useCallback(async (youtubeUrl: string) => {
    setIsStarting(true)
    setClientError('')
    try {
      const result = await client.createJob({ youtubeUrl })
      setJobId(result.jobId)
    } catch (error) {
      setClientError(messageOf(error, 'Không thể tạo công việc.'))
    } finally {
      setIsStarting(false)
    }
  }, [client])

  const cancel = useCallback(async () => {
    if (!jobId) return
    try {
      await client.cancelJob(jobId)
      setJob(await client.getJob(jobId))
    } catch (error) {
      setClientError(messageOf(error, 'Không thể hủy công việc.'))
    }
  }, [client, jobId])

  const retry = useCallback(async () => {
    if (!jobId) return
    setIsStarting(true)
    setClientError('')
    try {
      const result = await client.retryJob(jobId)
      setJobId(result.jobId)
    } catch (error) {
      setClientError(messageOf(error, 'Không thể thử lại công việc.'))
    } finally {
      setIsStarting(false)
    }
  }, [client, jobId])

  const reset = useCallback(() => {
    setJob(undefined)
    setJobId(undefined)
    setClientError('')
  }, [])

  return { job, clientError, isStarting, start, cancel, retry, reset }
}
