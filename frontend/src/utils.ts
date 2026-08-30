import type { InspectionStatus, ReviewDecision } from './types'
import type { Language } from './config/tenant'
import { translate } from './i18n'

export function formatDateTime(value: string, includeSeconds = false, language: Language = 'zh') {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
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

function containsHan(value: string) {
  return /[\u3400-\u9fff]/u.test(value)
}

export function formatAuditTitle(value: string, language: Language = 'zh') {
  const transition = value.match(/^([A-Z_]+)->([A-Z_]+)$/)
  if (transition) {
    const from = translate(language, `status.${transition[1]}` as never)
    const to = translate(language, `status.${transition[2]}` as never)
    return language === 'en' ? `Status change: ${from} → ${to}` : `状态变化：${from} → ${to}`
  }
  if (language === 'en') {
    const english: Record<string, string> = {
      'inspection.received': 'Image received',
      'inspection.state_changed': 'Inspection status updated',
      'review.required': 'Human review required',
      'review.completed': 'Human review completed',
      'quality_incident.created': 'Quality event created',
      'external_action.completed': 'External action completed',
    }
    if (value.includes('接收并校验图像')) return 'Image received and validated'
    if (value.includes('模型完成异常检测')) return 'Anomaly analysis completed'
    if (value.includes('策略触发')) return 'Policy triggered a controlled hold'
    if (value.includes('复核任务')) return 'Review task updated'
    if (value.includes('QMS 工单创建完成')) return 'QMS work order created'
    if (value.includes('质量事件')) return 'Quality event updated'
    return english[value] ?? (containsHan(value) ? 'Audit event' : value)
  }
  return auditTitleLabels[value] ?? value
}

export function formatAuditDetail(value: string, language: Language = 'zh') {
  if (language === 'en') {
    if (value === 'input and tenant context validated') return 'Image format, tenant, and product context passed validation.'
    if (value === 'model invocation started') return 'The anomaly service started analyzing the image.'
    if (value === 'immutable model result saved') return 'The score, heatmap, and model version were saved as immutable evidence.'
    if (value === 'external action execution started') return 'The system started the MES / QMS business action.'
    if (value === 'all external actions completed idempotently') return 'MES / QMS actions completed idempotently; retries cannot create duplicates.'
    if (value === 'quality incident created; external actions pending') return 'The quality event was created and is waiting for MES / QMS disposition.'
    if (value === 'UNKNOWN_ANOMALY') return 'A person confirmed an unknown anomaly that needs investigation.'
    if (value.includes('review_threshold') && value.includes('hold_threshold')) return 'The score falls between the human-review and batch-hold thresholds.'
    if (value.startsWith('{')) return 'A structured technical record was saved; use the correlation ID to investigate further.'
    if (value.includes('文件类型、尺寸与业务上下文校验通过')) return 'Image type, dimensions, and business context passed validation; SHA-256 was recorded.'
    if (value.includes('PatchCore 输出异常分数')) return 'PatchCore produced an anomaly score and pixel-level evidence; semantic defect remains unconfirmed.'
    if (value.includes('暂扣阈值')) return 'The score reached the batch-hold threshold; only a controlled hold and human review were created.'
    if (value.includes('质检员')) return 'A named inspector claimed the task; the optimistic-lock version was retained.'
    if (value.includes('QMS 工单创建完成')) return 'The QMS work order was created and linked to this quality event.'
    return containsHan(value) ? 'A structured audit detail is available; use the correlation ID for the next step.' : value
  }
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

export function formatAuditActor(value: string, language: Language = 'zh') {
  const labels: Record<string, string> = {
    'system:policy': '系统策略',
    'system:model-worker': '异常检测服务',
    'system:connector-worker': '外部系统连接服务',
    'demo-quality-manager': '演示质量经理',
  }
  if (language === 'en') {
    const english: Record<string, string> = {
      'system:policy': 'System policy',
      'system:model-worker': 'Anomaly service',
      'system:connector-worker': 'Connector service',
      'demo-quality-manager': 'Demo quality manager',
    }
    return english[value] ?? (containsHan(value) ? 'Named operator' : value)
  }
  return labels[value] ?? value
}

export function formatPolicyReason(value?: string, language: Language = 'zh') {
  if (!value) return language === 'en' ? 'No explainable policy reason was returned; the item was safely routed to human handling.' : '系统没有返回可解释的策略理由，已安全转交人工处理。'
  if (value.includes('review_threshold') && value.includes('hold_threshold')) return formatAuditDetail(value, language)
  if (value.includes('score') && value.includes('hold_threshold')) return language === 'en' ? 'The score reached the batch-hold threshold; the batch is paused for human confirmation.' : '分数达到暂扣线，批次先暂停并等待人工确认。'
  if (value.includes('score') && value.includes('review_threshold')) return language === 'en' ? 'The score reached the human-review range; a person must decide the next step.' : '分数低于人工复核线，当前策略允许继续流转。'
  return language === 'en' && containsHan(value) ? 'The policy reason is recorded; use the correlation ID for details.' : value
}

export function formatSource(value: string, language: Language = 'zh') {
  const labels: Record<string, string> = {
    'Web manual upload': '网页手动上传',
    'Blender synthetic demo': 'Blender 合成演示样本',
    'Edge Gateway': '现场接入程序',
  }
  if (language === 'en') {
    const english: Record<string, string> = {
      'Web manual upload': 'Web manual upload',
      'Blender synthetic demo': 'Blender synthetic demo',
      'Edge Gateway': 'Edge Gateway',
    }
    return english[value] ?? (containsHan(value) ? 'Recorded source' : value)
  }
  return labels[value] ?? value
}

export function formatStation(value: string, language: Language = 'zh') {
  if (language === 'zh') return value
  return value
    .replaceAll('终检', 'Final inspection')
    .replaceAll('涂装检查站', 'Paint inspection station')
    .replaceAll('瓶身环检单元', 'Bottle ring inspection cell')
    .replaceAll('工位', 'Station')
}
