import { AlertOctagon, LoaderCircle, RefreshCcw } from 'lucide-react'
import { ApiError } from '../api/client'

export function LoadingState({ label = '正在读取质量证据…' }: { label?: string }) {
  return (
    <div className="state-panel loading-state" role="status">
      <LoaderCircle className="spin" size={24} />
      <div><strong>{label}</strong><span>请勿关闭当前作业页</span></div>
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = error instanceof ApiError ? error : undefined
  return (
    <div className="state-panel error-state" role="alert">
      <AlertOctagon size={25} />
      <div className="state-panel-copy">
        <strong>{apiError?.message ?? '无法加载当前数据'}</strong>
        <span>{apiError?.nextStep ?? '请检查网络连接并重试。'}</span>
        {apiError?.correlationId && <code>关联 ID · {apiError.correlationId}</code>}
      </div>
      {onRetry && <button className="secondary-button" onClick={onRetry}><RefreshCcw size={15} />重试</button>}
    </div>
  )
}
