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

const auditTitleLabels: Record<string, string> = {
  'RECEIVED->VALIDATED': '图片与业务信息校验通过',
  'VALIDATED->INFERENCING': '开始分析图片',
  'INFERENCING->SCORED': '分析结果已保存',
  'SCORED->REVIEW_REQUIRED': '图片已转交人工确认',
  'SCORED->BATCH_HELD': '批次已暂扣并转交人工确认',
  'inspection.received': '系统收到图片',
  'inspection.state_changed': '检测状态已更新',
  'review.required': '需要人工确认',
  'review.completed': '人工复核已完成',
  'quality_incident.created': '质量事件已创建',
  'external_action.completed': '外部业务操作已完成',
}

export function formatAuditTitle(value: string) {
  const transition = value.match(/^([A-Z_]+)->([A-Z_]+)$/)
  if (transition) {
    const from = statusLabels[transition[1] as InspectionStatus] ?? transition[1]
    const to = statusLabels[transition[2] as InspectionStatus] ?? transition[2]
    return `状态变化：${from} → ${to}`
  }
  return auditTitleLabels[value] ?? value
}

export function formatAuditDetail(value: string) {
  if (value.includes('review_threshold') && value.includes('hold_threshold')) {
    const numbers = value.match(/\d+\.\d+/g)
    return numbers?.length === 3
      ? `分数 ${Number(numbers[1]).toFixed(2)} 位于人工复核线 ${Number(numbers[0]).toFixed(2)} 和暂扣线 ${Number(numbers[2]).toFixed(2)} 之间。`
      : '分数达到人工复核区间，已交给人工确认。'
  }
  if (value === 'input and tenant context validated') return '图片格式、当前工厂和产品信息已经校验。'
  if (value === 'model invocation started') return '异常检测服务开始分析图片。'
  if (value === 'immutable model result saved') return '分析分数、热力图和模型版本已经保存，不能被原地覆盖。'
  if (value === 'external action execution started') return '系统开始执行 MES / QMS 业务操作。'
  if (value === 'all external actions completed idempotently') return 'MES / QMS 操作均已完成，重复执行也不会产生重复记录。'
  if (value === 'quality incident created; external actions pending') return '质量事件已经创建，正在等待 MES / QMS 执行处置。'
  if (value === 'UNKNOWN_ANOMALY') return '人工确认存在未知异常，需要进一步调查。'
  if (value.startsWith('{') && value.includes('image_sha256')) return '原始图片已经保存，并生成唯一证据指纹。'
  if (value.startsWith('{')) {
    try {
      const detail = JSON.parse(value) as {
        status?: string
        attempts?: number
        external_reference?: string
        inspection_status?: InspectionStatus
      }
      if (detail.inspection_status) return `系统决定：${statusLabels[detail.inspection_status] ?? detail.inspection_status}。`
      if (detail.status) {
        const status = detail.status === 'SUCCEEDED' ? '成功' : detail.status
        const reference = detail.external_reference ? `，外部编号 ${detail.external_reference}` : ''
        return `外部业务操作${status}${reference}；共尝试 ${detail.attempts ?? 1} 次。`
      }
    } catch {
      return '系统已保存一条结构化技术记录，可通过关联编号进一步排查。'
    }
  }
  return value
}

export function formatAuditActor(value: string) {
  const labels: Record<string, string> = {
    'system:policy': '系统策略',
    'system:model-worker': '异常检测服务',
    'system:connector-worker': '外部系统连接服务',
    'demo-quality-manager': '演示质量经理',
  }
  return labels[value] ?? value
}

export function formatPolicyReason(value?: string) {
  if (!value) return '系统没有返回可解释的策略理由，已安全转交人工处理。'
  if (value.includes('review_threshold') && value.includes('hold_threshold')) return formatAuditDetail(value)
  if (value.includes('score') && value.includes('hold_threshold')) return '分数达到暂扣线，批次先暂停并等待人工确认。'
  if (value.includes('score') && value.includes('review_threshold')) return '分数低于人工复核线，当前策略允许继续流转。'
  return value
}

export function formatSource(value: string) {
  const labels: Record<string, string> = {
    'Web manual upload': '网页手动上传',
    'Blender synthetic demo': 'Blender 合成演示样本',
    'Edge Gateway': '现场接入程序',
  }
  return labels[value] ?? value
}
