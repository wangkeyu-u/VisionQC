import { createRoot } from 'react-dom/client'
import { AppRoutes } from './App'
import './styles.css'

async function prepare() {
  if (import.meta.env.VITE_USE_MOCKS !== 'false') {
    const { worker } = await import('./mocks/browser')
    const startResult = await Promise.race([
      worker.start({ onUnhandledRequest: 'bypass', quiet: true }).then(() => 'ready' as const),
      new Promise<'timeout'>((resolve) => window.setTimeout(() => resolve('timeout'), 2_000)),
    ])
    if (startResult === 'timeout') {
      console.warn('VisionQC mock worker did not become ready within 2 seconds; rendering the UI in degraded mode.')
    }
  }
}

void prepare()
  .catch((error) => console.warn('VisionQC mock worker could not start; rendering the UI in degraded mode.', error))
  .finally(() => createRoot(document.getElementById('root')!).render(<AppRoutes />))
