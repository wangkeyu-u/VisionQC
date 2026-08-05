import { AlertTriangle, CheckCircle2, CircleDot, Clock3, LoaderCircle, ShieldAlert } from 'lucide-react'
import type { InspectionStatus } from '../types'
import { statusLabels, statusTone } from '../utils'

interface StatusBadgeProps {
  status: InspectionStatus | 'PENDING' | 'EXECUTING' | 'COMPLETED' | 'FAILED' | 'OPEN' | 'CLAIMED'
    | 'ONLINE' | 'DEGRADED' | 'STALE' | 'OFFLINE' | 'STARTING' | 'STOPPING'
  label?: string
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, label, size = 'md' }: StatusBadgeProps) {
  const tone = statusTone(status)
  const Icon = tone === 'success'
    ? CheckCircle2
    : tone === 'danger'
      ? ShieldAlert
      : tone === 'warning'
        ? AlertTriangle
        : ['INFERENCING', 'EXECUTING'].includes(status)
          ? LoaderCircle
          : ['RECEIVED', 'PENDING'].includes(status)
            ? Clock3
            : CircleDot
  const fallbackLabels: Record<string, string> = {
    PENDING: '待执行', EXECUTING: '执行中', COMPLETED: '已完成', FAILED: '失败', OPEN: '待认领', CLAIMED: '已认领',
    ONLINE: '在线', DEGRADED: '有积压', STALE: '心跳陈旧', OFFLINE: '离线', STARTING: '启动中', STOPPING: '停止中',
  }
  return (
    <span className={`status-badge ${tone} ${size}`}>
      <Icon size={size === 'sm' ? 13 : 15} aria-hidden="true" />
      {label ?? statusLabels[status as InspectionStatus] ?? fallbackLabels[status] ?? status}
    </span>
  )
}
