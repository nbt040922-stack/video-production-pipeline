import type { PipelineClient } from './pipeline-client'
import { BackendPipelineClient } from './backend-pipeline-client'
import { MockPipelineClient } from './mock-pipeline-client'

export function createPipelineClient(): PipelineClient {
  return import.meta.env.PROD || import.meta.env.VITE_PIPELINE_MODE === 'backend'
    ? new BackendPipelineClient(import.meta.env.VITE_API_BASE_URL || '')
    : new MockPipelineClient()
}
