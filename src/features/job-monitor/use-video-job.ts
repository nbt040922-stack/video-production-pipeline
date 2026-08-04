import { useCallback, useEffect, useState } from 'react'
import type { PipelineClient } from '../../services/pipeline-client'
import type { VideoJob } from '../../types/job'

const terminalStatuses = new Set(['completed', 'failed', 'cancelled'])

export function useVideoJob(client: PipelineClient) {
  const [job, setJob] = useState<VideoJob>()
  const [jobId, setJobId] = useState<string>()
  const [isStarting, setIsStarting] = useState(false)

  useEffect(() => {
    if (!jobId) return
    let active = true
    let timer: ReturnType<typeof setInterval>

    const refresh = async () => {
      const next = await client.getJob(jobId)
      if (!active) return
      setJob(next)
      if (terminalStatuses.has(next.status)) clearInterval(timer)
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
    try {
      const result = await client.createJob({ youtubeUrl })
      setJobId(result.jobId)
    } finally {
      setIsStarting(false)
    }
  }, [client])

  const cancel = useCallback(async () => {
    if (!jobId) return
    await client.cancelJob(jobId)
    setJob(await client.getJob(jobId))
  }, [client, jobId])

  const reset = useCallback(() => {
    setJob(undefined)
    setJobId(undefined)
  }, [])

  return { job, isStarting, start, cancel, reset }
}
