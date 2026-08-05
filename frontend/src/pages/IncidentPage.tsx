import { useCallback, useEffect, useState } from 'react'
import { Link, useRoute } from 'wouter'
import {
  ArrowLeft,
  ArrowUpRight,
  Boxes,
  Check,
  CircleDashed,
  ClipboardList,
  ExternalLink,
  Fingerprint,
  LockKeyhole,
  RotateCcw,
  ShieldCheck,
  TicketCheck,
  TriangleAlert,
  UserRound,
} from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { Timeline } from '../components/Timeline'
import type { QualityIncident } from '../types'
import { formatDateTime } from '../utils'

const incidentStatusLabels = { OPEN: '已创建', ACTION_PENDING: '处置待执行', ACTION_EXECUTING: '处置执行中', VERIFYING: '等待验证', CLOSED: '已关闭', ESCALATED: '已升级' }
const dispositionLabels = { REWORK: '返工', SCRAP: '报废', INVESTIGATE: '调查' }
const transientIncidentStatuses = ['ACTION_PENDING', 'ACTION_EXECUTING']

export function IncidentPage() {
  const [, params] = useRoute('/incidents/:id')
  const id = params?.id ?? ''
  const [incident, setIncident] = useState<QualityIncident | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(async () => {
    try { setError(null); setIncident(await visionQcApi.getIncident(id)) } catch (caught) { setError(caught) }
  }, [id])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!incident || !transientIncidentStatuses.includes(incident.status)) return
    const timeout = window.setTimeout(() => void load(), 900)
    return () => window.clearTimeout(timeout)
  }, [incident, load])

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!incident) return <div className="page"><LoadingState label="正在重建质量事件时间线…" /></div>
  const isClosed = incident.status === 'CLOSED'
  const hasOutcome = Boolean(incident.outcome)
  const hasVerification = Boolean(incident.verificationRecord)

  return (
    <div className="page incident-page">
      <div className="breadcrumb"><Link href="/reviews"><ArrowLeft size={14} />复核队列</Link><span>/</span><strong>{incident.id}</strong></div>
      <div className="detail-heading incident-heading">
        <div><span className="page-kicker">质量事件 · 处置闭环</span><div className="title-line"><h1>质量事件 {incident.id}</h1><StatusBadge status={incident.status} label={incidentStatusLabels[incident.status]} /></div><p>由人工确认结果创建 · Mock MES/QMS 闭环演示</p></div>
        <Link className="secondary-button" href={`/inspections/${incident.inspectionId}`}>查看原始证据<ExternalLink size={15} /></Link>
      </div>

      <div className="incident-summary-grid">
        <section className="incident-hero panel">
          <div className="incident-band"><span>处置</span><strong>{dispositionLabels[incident.disposition]}</strong><i /> <span>严重度</span><strong>{incident.severity === 'MAJOR' ? '主要' : '关键'}</strong></div>
          <div className="incident-title"><div className="incident-icon"><TriangleAlert size={27} /></div><div><span>人工确认不合格</span><h2>{incident.productCode} · {incident.batchNo}</h2><p>已创建唯一主质量事件；模型异常分数保留为证据，不作为根因事实。</p></div></div>
          <dl className="incident-facts">
            <div><dt><UserRound size={15} />事件负责人</dt><dd>{incident.owner}</dd></div>
            <div><dt><Boxes size={15} />工位</dt><dd>{incident.station}</dd></div>
            <div><dt><Fingerprint size={15} />检测记录</dt><dd><Link href={`/inspections/${incident.inspectionId}`}>{incident.inspectionId}</Link></dd></div>
            <div><dt><ClipboardList size={15} />创建时间</dt><dd>{formatDateTime(incident.createdAt, true)}</dd></div>
          </dl>
        </section>

        <section className="panel closure-gate">
          <div className="section-title"><div><span>关闭门槛</span><h2>关闭门槛</h2></div><LockKeyhole size={19} /></div>
          <ul>
            <li className="done"><Check size={15} /><span><strong>具名处置决定</strong><small>{incident.evidence.decisionActor} · {dispositionLabels[incident.disposition]}</small></span></li>
            <li className="done"><Check size={15} /><span><strong>事件负责人</strong><small>{incident.owner}</small></span></li>
            <li className={hasOutcome ? 'done' : undefined}>{hasOutcome ? <Check size={15} /> : <CircleDashed size={15} />}<span><strong>调查结论</strong><small>{incident.outcome ?? '等待 QMS 更新'}</small></span></li>
            <li className={hasVerification ? 'done' : undefined}>{hasVerification ? <Check size={15} /> : <CircleDashed size={15} />}<span><strong>处置验证记录</strong><small>{incident.verificationRecord ?? '尚未提交'}</small></span></li>
          </ul>
          <button disabled className="secondary-button full-button">{isClosed ? <Check size={15} /> : <LockKeyhole size={15} />}{isClosed ? '关闭门槛已满足 · 事件已关闭' : '条件未满足，不能关闭'}</button>
        </section>
      </div>

      <section className="panel decision-evidence-card">
        <div className="section-title"><div><span>人工决定证据</span><h2>人工决定与版本证据</h2></div><ShieldCheck size={20} /></div>
        <blockquote>“{incident.evidence.decisionReason}”</blockquote>
        <div className="decision-evidence-grid">
          <span><small>操作者</small><strong>{incident.evidence.decisionActor}</strong></span>
          <span><small>异常分数</small><strong>{incident.evidence.score.toFixed(2)} <em>模型证据</em></strong></span>
          <span><small>模型版本</small><strong>{incident.evidence.modelVersion}</strong></span>
          <span><small>策略版本</small><strong>{incident.evidence.policyVersion}</strong></span>
        </div>
      </section>

      <section className="panel connector-section">
        <div className="section-title"><div><span>幂等外部操作</span><h2>外部业务操作</h2></div><small><i />Mock MES / QMS</small></div>
        <div className="connector-grid">
          {incident.externalActions.map((action) => (
            <article key={action.id}>
              <div className="connector-head"><div className={action.system === 'Mock MES' ? 'mes' : 'qms'}>{action.system === 'Mock MES' ? <Boxes size={19} /> : <TicketCheck size={19} />}</div><span><strong>{action.system}</strong><small>{action.action}</small></span><StatusBadge status={action.status} size="sm" /></div>
              <p>{action.message}</p>
              <dl><div><dt>尝试次数</dt><dd>{action.attempts}</dd></div><div><dt>外部编号</dt><dd>{action.externalRef ?? '—'}</dd></div><div className="wide"><dt>幂等键</dt><dd><code>{action.idempotencyKey}</code></dd></div><div className="wide"><dt>最后更新</dt><dd>{formatDateTime(action.updatedAt, true)}</dd></div></dl>
              {action.status === 'FAILED' && <button className="secondary-button"><RotateCcw size={14} />授权重放</button>}
              {action.externalRef && <button className="text-button">查看模拟记录<ArrowUpRight size={14} /></button>}
            </article>
          ))}
        </div>
        <div className="idempotency-note"><ShieldCheck size={17} /><span><strong>未发现重复副作用。</strong> QMS 首次超时后以相同幂等键重试并取回原工单，最终仅关联一个外部记录。</span></div>
      </section>

      <section className="panel incident-timeline-panel">
        <div className="section-title"><div><span>完整审计链</span><h2>检测到处置的完整时间线</h2></div><div className="append-only-chip"><LockKeyhole size={13} />只追加审计</div></div>
        <Timeline events={incident.timeline} />
      </section>
    </div>
  )
}
