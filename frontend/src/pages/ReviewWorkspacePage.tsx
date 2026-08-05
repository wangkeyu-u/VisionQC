import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useRoute } from 'wouter'
import {
  AlertOctagon,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleHelp,
  ClipboardCheck,
  RotateCcw,
  Search,
  ShieldAlert,
  Trash2,
  X,
} from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { EvidenceViewer } from '../components/EvidenceViewer'
import { StatusBadge } from '../components/StatusBadge'
import type { Inspection, ReviewDecision, ReviewReceipt, ReviewTask } from '../types'
import { decisionLabels, formatDateTime, formatScore } from '../utils'

const decisions = [
  { value: 'PASS' as const, label: '合格', icon: CheckCircle2, shortcut: '1', copy: '批准当前产品继续流转' },
  { value: 'REWORK' as const, label: '返工', icon: RotateCcw, shortcut: '2', copy: '创建返工处置并保持批次受控' },
  { value: 'SCRAP' as const, label: '报废', icon: Trash2, shortcut: '3', copy: '提交报废审批，不会由模型自动执行' },
  { value: 'INVESTIGATE' as const, label: '调查', icon: Search, shortcut: '4', copy: '创建质量事件并调查未知根因' },
  { value: 'UNABLE_TO_DECIDE' as const, label: '无法判断', icon: CircleHelp, shortcut: '5', copy: '升级给质量主管，不默认放行' },
]

const reasonOptions: Record<ReviewDecision, { value: string; label: string }[]> = {
  PASS: [{ value: 'NO_VISIBLE_NONCONFORMANCE', label: '未发现影响质量的可见不符合' }],
  REWORK: [{ value: 'SURFACE_CONTAMINATION', label: '表面污染，可返工清洁' }, { value: 'LEAD_ALIGNMENT', label: '引脚偏位，可返工校正' }],
  SCRAP: [{ value: 'STRUCTURAL_DAMAGE', label: '结构性损伤，不可返工' }, { value: 'CRITICAL_DIMENSION', label: '关键尺寸不符合' }],
  INVESTIGATE: [{ value: 'UNKNOWN_ANOMALY', label: '异常来源未知，需调查' }, { value: 'BATCH_PATTERN', label: '同批次出现聚集模式' }],
  UNABLE_TO_DECIDE: [{ value: 'INSUFFICIENT_EVIDENCE', label: '证据不足' }, { value: 'STANDARD_UNCLEAR', label: '适用质量标准不明确' }],
}

export function ReviewWorkspacePage() {
  const [, params] = useRoute('/reviews/:taskId')
  const taskId = params?.taskId ?? ''
  const [, navigate] = useLocation()
  const [task, setTask] = useState<ReviewTask | null>(null)
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [decision, setDecision] = useState<ReviewDecision | null>(null)
  const [reasonCode, setReasonCode] = useState('')
  const [note, setNote] = useState('')
  const [modelFeedback, setModelFeedback] = useState<'FALSE_POSITIVE' | 'POSSIBLE_MISS' | 'NONE'>('NONE')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [impactConfirmed, setImpactConfirmed] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<ReviewReceipt | null>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const tasks = await visionQcApi.listReviews()
      const selected = tasks.find((item) => item.id === taskId)
      if (!selected) throw new Error('未找到复核任务')
      const evidence = await visionQcApi.getInspection(selected.inspectionId)
      setTask(selected)
      setInspection(evidence)
    } catch (caught) { setError(caught) }
  }, [taskId])
  useEffect(() => { void load() }, [load])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (receipt || confirmOpen || ['INPUT', 'TEXTAREA', 'SELECT'].includes((event.target as HTMLElement).tagName)) return
      const match = decisions.find((item) => item.shortcut === event.key)
      if (match) chooseDecision(match.value)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  const chosen = useMemo(() => decisions.find((item) => item.value === decision), [decision])
  const isHighRisk = decision ? ['REWORK', 'SCRAP', 'INVESTIGATE'].includes(decision) : false

  function chooseDecision(next: ReviewDecision) {
    setDecision(next)
    setReasonCode(reasonOptions[next][0]?.value ?? '')
    setFormError(null)
  }

  function requestSubmit() {
    if (!decision) return setFormError('请选择一个质量结论。')
    if (!reasonCode) return setFormError('请选择决定理由。')
    if ((decision !== 'PASS' || isHighRisk) && note.trim().length < 8) return setFormError('请用至少 8 个字记录现场观察或判断依据。')
    if (isHighRisk) {
      setImpactConfirmed(false)
      setConfirmOpen(true)
    } else {
      void submitDecision(true)
    }
  }

  async function submitDecision(confirmed: boolean) {
    if (!decision || !task) return
    setSubmitting(true)
    setFormError(null)
    try {
      const nextReceipt = await visionQcApi.submitReviewDecision(task.id, {
        decision,
        reasonCode,
        note,
        expectedVersion: task.version,
        modelFeedback,
        impactConfirmed: confirmed,
      })
      setReceipt(nextReceipt)
      setConfirmOpen(false)
    } catch (caught) {
      setConfirmOpen(false)
      setError(caught)
    } finally { setSubmitting(false) }
  }

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!task || !inspection) return <div className="page"><LoadingState label="正在组装复核证据…" /></div>

  if (receipt) {
    return (
      <div className="page review-receipt-page">
        <div className="review-receipt panel">
          <div className="receipt-mark"><Check size={35} /></div>
          <span className="page-kicker">决定已记录 · 只追加审计</span>
          <h1>复核决定已具名提交</h1>
          <p>该决定已写入审计链，不能原地覆盖。后续更正需要新建事件并保留本次记录。</p>
          <dl>
            <div><dt>质量结论</dt><dd>{decision ? decisionLabels[decision] : '—'}</dd></div>
            <div><dt>操作者</dt><dd>{receipt.actor}</dd></div>
            <div><dt>提交时间</dt><dd>{formatDateTime(receipt.submittedAt, true)}</dd></div>
            <div><dt>决策记录</dt><dd><code>{receipt.decisionId}</code></dd></div>
            <div><dt>关联 ID</dt><dd><code>{receipt.correlationId}</code></dd></div>
          </dl>
          {receipt.incidentId ? (
            <div className="receipt-next"><ShieldAlert size={20} /><span><strong>已创建唯一质量事件</strong><small>批次保持受控；MES/QMS 外部动作将使用幂等键执行。</small></span></div>
          ) : (
            <div className="receipt-next success"><CheckCircle2 size={20} /><span><strong>已批准放行</strong><small>本次未创建不合格事件或 QMS 工单。</small></span></div>
          )}
          <div className="receipt-actions">
            <button className="secondary-button" onClick={() => navigate('/reviews')}>返回复核队列</button>
            {receipt.incidentId && <Link className="primary-button" href={`/incidents/${receipt.incidentId}`}>查看质量事件<ArrowRight size={16} /></Link>}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page review-workspace-page">
      <div className="breadcrumb"><Link href="/reviews"><ArrowLeft size={14} />复核队列</Link><span>/</span><strong>{task.id}</strong></div>
      <div className="review-workspace-heading">
        <div><span className="page-kicker">具名复核 · 任务 v{task.version}</span><div className="title-line"><h1>质量复核工作台</h1><StatusBadge status={inspection.status} /></div><p>{inspection.context.batchNo} · {inspection.context.productCode} · {inspection.context.station}</p></div>
        <div className="sla-card"><span>复核 SLA</span><strong>{formatDateTime(task.slaAt)}</strong><small>{task.assignee ? `已由 ${task.assignee} 认领` : '待认领'}</small></div>
      </div>

      <div className="review-workspace-grid">
        <div className="review-evidence-column">
          <EvidenceViewer inspection={inspection} compact />
          <div className="evidence-strip">
            <div><span>异常分数</span><strong>{formatScore(inspection.inference?.score)}</strong></div>
            <div><span>复核阈值</span><strong>{inspection.policy?.reviewThreshold.toFixed(2) ?? '—'}</strong></div>
            <div><span>暂扣阈值</span><strong>{inspection.policy?.holdThreshold.toFixed(2) ?? '—'}</strong></div>
            <div><span>模型版本</span><strong>{inspection.inference?.modelVersion ?? '失败'}</strong></div>
            <div><span>策略版本</span><strong>{inspection.policy?.version.split('-').at(-1) ?? '安全降级'}</strong></div>
          </div>
          <div className="review-context panel">
            <span><strong>模型路由：</strong>{inspection.policy?.reason ?? '模型不可用，安全降级至人工处理'}</span>
            <span><strong>证据指纹：</strong><code>{inspection.image.sha256.slice(0, 18)}…</code></span>
          </div>
        </div>

        <aside className="decision-desk panel">
          <div className="decision-desk-head"><div><span>质量决定</span><h2>提交人工结论</h2></div><ClipboardCheck size={22} /></div>
          <p className="decision-guidance">先检查原图与热力图，再依据现场标准做出结论。数字键 1–5 可快速选择。</p>
          <div className="decision-options" role="radiogroup" aria-label="质量结论">
            {decisions.map(({ value, label, icon: Icon, shortcut, copy }) => (
              <button key={value} role="radio" aria-checked={decision === value} className={decision === value ? `selected decision-${value.toLowerCase()}` : ''} onClick={() => chooseDecision(value)}>
                <span className="decision-icon"><Icon size={18} /></span><span><strong>{label}</strong><small>{copy}</small></span><kbd>{shortcut}</kbd>
              </button>
            ))}
          </div>

          {decision && (
            <div className="decision-fields">
              <label><span>决定理由 <b>*</b></span><select value={reasonCode} onChange={(event) => setReasonCode(event.target.value)}>{reasonOptions[decision].map((reason) => <option key={reason.value} value={reason.value}>{reason.label}</option>)}</select></label>
              <label><span>现场观察 {decision !== 'PASS' && <b>*</b>}</span><textarea rows={4} placeholder="描述你在原图中观察到的事实；不要把模型响应写成已确认根因。" value={note} onChange={(event) => setNote(event.target.value)} /></label>
              <label><span>模型反馈</span><select value={modelFeedback} onChange={(event) => setModelFeedback(event.target.value as typeof modelFeedback)}><option value="NONE">不标记</option><option value="FALSE_POSITIVE">疑似模型误检</option><option value="POSSIBLE_MISS">疑似模型漏检</option></select><small>反馈只进入独立评测集，不会自动更新生产模型。</small></label>
            </div>
          )}

          {formError && <div className="inline-error" role="alert"><AlertOctagon size={15} />{formError}</div>}
          <div className="decision-submit">
            <span><ShieldAlert size={16} />决定将记录操作者、时间与任务版本</span>
            <button className={`primary-button ${isHighRisk ? 'danger-button' : ''}`} onClick={requestSubmit} disabled={!decision || submitting}>{submitting ? '正在提交…' : chosen ? `提交“${chosen.label}”` : '请选择结论'}<ArrowRight size={16} /></button>
          </div>
        </aside>
      </div>

      {confirmOpen && decision && (
        <div className="modal-backdrop" role="presentation">
          <section className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
            <button className="dialog-close" aria-label="关闭确认窗口" onClick={() => setConfirmOpen(false)}><X size={18} /></button>
            <div className="dialog-danger-icon"><ShieldAlert size={28} /></div>
            <span className="page-kicker">高风险确认</span>
            <h2 id="confirm-title">确认提交“{decisionLabels[decision]}”处置</h2>
            <p>{decision === 'SCRAP' ? '本次提交将创建报废审批请求；在质量主管批准前不会执行报废。' : decision === 'REWORK' ? '本次提交将保持批次受控并创建返工质量事件。' : '本次提交将保持批次暂扣并创建调查质量事件。'}</p>
            <dl>
              <div><dt>影响批次</dt><dd>{inspection.context.batchNo}</dd></div>
              <div><dt>检测记录</dt><dd>{inspection.id}</dd></div>
              <div><dt>标准理由</dt><dd>{reasonOptions[decision].find((reason) => reason.value === reasonCode)?.label}</dd></div>
              <div><dt>当前操作者</dt><dd>林知夏 / Inspector</dd></div>
            </dl>
            <label className="impact-check"><input type="checkbox" checked={impactConfirmed} onChange={(event) => setImpactConfirmed(event.target.checked)} /><span><strong>我已核对影响对象与现场证据</strong><small>我理解异常分数不是缺陷确认，本决定基于人工检查与适用标准。</small></span></label>
            <div className="dialog-actions"><button className="secondary-button" onClick={() => setConfirmOpen(false)}>返回检查</button><button className="primary-button danger-button" disabled={!impactConfirmed || submitting} onClick={() => void submitDecision(true)}>{submitting ? '写入审计链…' : '确认并提交'}<ArrowRight size={16} /></button></div>
          </section>
        </div>
      )}
    </div>
  )
}
