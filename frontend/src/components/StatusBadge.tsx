import { AlertTriangle, CheckCircle2, CircleDot, Clock3, LoaderCircle, ShieldAlert } from 'lucide-react'
import type { InspectionStatus } from '../types'
import { statusLabel } from '../i18n'
import { useI18n } from '../hooks/useI18n'
import { statusTone } from '../utils'

interface StatusBadgeProps {
  status: InspectionStatus | 'PENDING' | 'EXECUTING' | 'COMPLETED' | 'FAILED' | 'OPEN' | 'CLAIMED'
    | 'ONLINE' | 'DEGRADED' | 'STALE' | 'OFFLINE' | 'STARTING' | 'STOPPING' | string
  label?: string
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, label, size = 'md' }: StatusBadgeProps) {
  const { language } = useI18n()
  const tone = statusTone(status)
  const Icon = tone === 'success' ? CheckCircle2 : tone === 'danger' ? ShieldAlert : tone === 'warning' ? AlertTriangle : ['INFERENCING', 'EXECUTING'].includes(status) ? LoaderCircle : ['RECEIVED', 'PENDING'].includes(status) ? Clock3 : CircleDot
  return <span className={`status-badge ${tone} ${size}`}><Icon size={size === 'sm' ? 13 : 15} aria-hidden="true" />{label ?? statusLabel(language, status)}</span>
}
