import { AlertOctagon, LoaderCircle, RefreshCcw } from 'lucide-react'
import { ApiError } from '../api/client'
import { useI18n } from '../hooks/useI18n'

export function LoadingState({ label }: { label?: string }) {
  const { t } = useI18n()
  return <div className="state-panel loading-state" role="status"><LoaderCircle className="spin" size={24} /><div><strong>{label ?? t('common.loading')}</strong><span>{t('common.loading')}</span></div></div>
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n()
  const apiError = error instanceof ApiError ? error : undefined
  return <div className="state-panel error-state" role="alert"><AlertOctagon size={25} /><div className="state-panel-copy"><strong>{apiError?.message ?? t('error.load')}</strong><span>{apiError?.nextStep ?? t('error.next')}</span>{apiError?.correlationId && <code>Correlation ID · {apiError.correlationId}</code>}</div>{onRetry && <button className="secondary-button" onClick={onRetry}><RefreshCcw size={15} />{t('common.retry')}</button>}</div>
}
