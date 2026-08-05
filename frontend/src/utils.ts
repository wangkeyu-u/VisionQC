import type { InspectionStatus, ReviewDecision } from './types'

export function formatDateTime(value: string, includeSeconds = false) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: includeSeconds ? '2-digit' : undefined,
    hour12: false,
  }).format(date)
}

export function formatScore(score?: number) {
  return score === undefined ? '—' : score.toFixed(2)
}

export const statusLabels: Record<InspectionStatus, string> = {
  RECEIVED: '已接收',
  VALIDATED: '已校验',
  INFERENCING: '推理中',
  SCORED: '已评分',
  AUTO_RELEASED: '自动放行',
  REVIEW_REQUIRED: '等待复核',
  BATCH_HELD: '批次暂扣',
  INFERENCE_FAILED: '推理失败',
  RELEASE_APPROVED: '人工放行',
  NONCONFORMANCE_CONFIRMED: '人工确认不合格',
  ACTION_PENDING: '处置待执行',
  ACTION_EXECUTING: '处置执行中',
  ACTION_COMPLETED: '处置已完成',
  VERIFYING: '等待验证',
  ESCALATED: '已升级',
  CLOSED: '已关闭',
}

export const decisionLabels: Record<ReviewDecision, string> = {
  PASS: '合格',
  REWORK: '返工',
  SCRAP: '报废',
  INVESTIGATE: '调查',
  UNABLE_TO_DECIDE: '无法判断',
}

export function statusTone(status: InspectionStatus | string) {
  if (['AUTO_RELEASED', 'RELEASE_APPROVED', 'COMPLETED', 'CLOSED', 'ONLINE'].includes(status)) return 'success'
  if (['BATCH_HELD', 'INFERENCE_FAILED', 'FAILED', 'NONCONFORMANCE_CONFIRMED', 'OFFLINE'].includes(status)) return 'danger'
  if (['REVIEW_REQUIRED', 'VERIFYING', 'ACTION_PENDING', 'PENDING', 'DEGRADED', 'STALE', 'STARTING', 'STOPPING'].includes(status)) return 'warning'
  return 'info'
}

export function makeIdempotencyKey() {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}
