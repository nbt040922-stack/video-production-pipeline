import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { createPipelineClient } from './services/client-factory'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App client={createPipelineClient()} />
  </StrictMode>,
)
