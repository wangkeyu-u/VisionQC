import { useCallback, useEffect, useState } from 'react'
import { Link, useRoute } from 'wouter'
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Boxes,
  Clock3,
  Cpu,
  Fingerprint,
  Gauge,
  MapPin,
  ScanLine,
  ShieldAlert,
} from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { EvidenceViewer } from '../components/EvidenceViewer'
import { StatusBadge } from '../components/StatusBadge'
import { Timeline } from '../components/Timeline'
import type { Inspection } from '../types'
import { formatDateTime, formatPolicyReason, formatScore, formatSource } from '../utils'

const transientStatuses = ['RECEIVED', 'VALIDATED', 'INFERENCING', 'SCORED']

export function InspectionPage() {
  const [, params] = useRoute('/inspections/:id')
  const id = params?.id ?? ''
  const [inspection, setInspection] = useState<Inspection | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      setInspection(await visionQcApi.getInspection(id))
    } catch (caught) {
      setError(caught)
    }
  }, [id])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!inspection || !transientStatuses.includes(inspection.status)) return
    const timeout = window.setTimeout(() => void load(), 900)
    return () => window.clearTimeout(timeout)
  }, [inspection, load])

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!inspection) return <div className="page"><LoadingState label="正在装载检测证据…" /></div>

  const { inference, policy } = inspection
  const isTransient = transientStatuses.includes(inspection.status)

  return (
    <div className="page inspection-page">
      <div className="breadcrumb"><Link href="/"><ArrowLeft size={14} />检测任务</Link><span>/</span><strong>{inspection.id}</strong></div>
      <div className="detail-heading">
        <div>
          <span className="page-kicker">图片检测结果 · {inspection.context.productCode}</span>
          <div className="title-line"><h1>图片检测结果</h1><StatusBadge status={inspection.status} /></div>
          <p>批次 {inspection.context.batchNo} · 工位 {inspection.context.station} · 拍摄于 {formatDateTime(inspection.context.capturedAt, true)}</p>
        </div>
        {inspection.reviewTaskId && (
          <Link className="primary-button" href={`/reviews/${inspection.reviewTaskId}`}>由我确认这张图片<ArrowRight size={17} /></Link>
        )}
      </div>

      {isTransient && (
        <div className="processing-ribbon" role="status">
          <ScanLine className="scan-icon" size={20} />
          <div><strong>任务正在处理</strong><span>状态会自动更新。当前证据已持久化，离开页面不会丢失任务。</span></div>
          <code>{inspection.correlationId}</code>
        </div>
      )}

      {inspection.failure && (
        <div className="failure-banner" role="alert">
          <ShieldAlert size={24} />
          <div><strong>{inspection.failure.message}</strong><p>{inspection.failure.nextStep}</p><code>{inspection.failure.code} · {inspection.correlationId}</code></div>
        </div>
      )}

      {inspection.qualityFlags && inspection.qualityFlags.length > 0 && (
        <div className="quality-flag-banner" role="status">
          <ShieldAlert size={18} /><span><strong>采集质量门禁已触发：</strong>{inspection.qualityFlags.join('、')}。系统没有把这张图自动放行，已转人工复核。</span>
        </div>
      )}

      <div className="inspection-grid">
        <div className="inspection-main">
          <EvidenceViewer inspection={inspection} />

          <section className="panel evidence-metadata">
            <div className="section-title"><div><span>车身数字质量档案 · Digital quality record</span><h2>样本与生产上下文</h2></div><small>接收后只读</small></div>
            <dl className="metadata-grid">
              <div><dt><Boxes size={15} />产品 / 版本</dt><dd>{inspection.context.productCode} · {inspection.context.productRevision}</dd></div>
              <div><dt><Fingerprint size={15} />批次号</dt><dd>{inspection.context.batchNo}</dd></div>
              <div><dt><MapPin size={15} />工位</dt><dd>{inspection.context.station}</dd></div>
              <div><dt><Clock3 size={15} />采集时间</dt><dd>{formatDateTime(inspection.context.capturedAt, true)}</dd></div>
              <div className="wide"><dt><Fingerprint size={15} />原图 SHA-256</dt><dd><code>{inspection.image.sha256}</code></dd></div>
              <div><dt>图片来源</dt><dd>{formatSource(inspection.context.source)}</dd></div>
              {Object.entries(inspection.context.metadata ?? {}).filter(([key]) => key !== 'quality_flags').slice(0, 12).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}
            </dl>
          </section>
        </div>

        <aside className="inspection-side">
          <section className="panel score-card">
            <div className="section-title"><div><span>系统提示</span><h2>可疑程度</h2></div><Gauge size={20} /></div>
            <div className="score-readout"><strong>{formatScore(inference?.score)}</strong><span>/ 1.00</span></div>
            {inference && policy ? (
              <>
                <div className="threshold-meter" aria-label={`异常分数 ${inference.score}，复核阈值 ${policy.reviewThreshold}，暂扣阈值 ${policy.holdThreshold}`}>
                  <div className="meter-zones"><i /><i /><i /></div>
                  <span className="meter-marker review" style={{ left: `${policy.reviewThreshold * 100}%` }}><b>复核</b></span>
                  <span className="meter-marker hold" style={{ left: `${policy.holdThreshold * 100}%` }}><b>暂扣</b></span>
                  <span className="score-marker" style={{ left: `${inference.score * 100}%` }}><b>{inference.score.toFixed(2)}</b></span>
                </div>
                <div className="threshold-labels"><span>自动放行区</span><span>人工复核区</span><span>暂扣复核区</span></div>
                <div className="policy-result">
                  <AlertTriangle size={18} />
                  <div><strong>{policy.decision === 'BATCH_HOLD_AND_REVIEW' ? '批次已暂时停止，等待人工确认' : policy.decision === 'AUTO_RELEASE' ? '分数低于复核线，策略允许放行' : '这张图片需要人工确认'}</strong><span>{formatPolicyReason(policy.reason)}</span></div>
                </div>
              </>
            ) : <p className="muted-copy">模型未返回有效结果，策略已执行安全降级。</p>}
          </section>

          <section className="panel model-card">
            <details className="technical-details">
              <summary><span><Cpu size={18} /><strong>技术追溯信息</strong><small>供技术人员和审核人员查看</small></span><span>展开</span></summary>
              <dl>
              <div><dt>模型</dt><dd>{inference ? `${inference.modelId}@${inference.modelVersion}` : '未完成'}</dd></div>
              <div><dt>特征库</dt><dd>{inference?.featureBankVersion ?? '—'}</dd></div>
              <div><dt>策略</dt><dd>{policy?.version ?? '安全降级策略'}</dd></div>
              <div><dt>推理耗时</dt><dd>{inference ? `${inference.latencyMs} ms` : '—'}</dd></div>
              <div><dt>运行设备</dt><dd>{inference?.device ?? '—'}</dd></div>
              <div><dt>关联 ID</dt><dd><code>{inspection.correlationId}</code></dd></div>
              </dl>
            </details>
          </section>

          <section className="semantic-boundary">
            <span>理解这份结果</span>
            <strong>“看起来可疑”不等于“已经确认有缺陷”</strong>
            <p>系统只比较图片与正常样本的差异。缺陷是什么、为什么发生、该如何处置，仍需要人根据现场标准确认。</p>
          </section>
        </aside>
      </div>

      <section className="panel timeline-panel">
        <div className="section-title"><div><span>只追加审计</span><h2>审计时间线</h2></div><small>普通用户不可修改或删除</small></div>
        <Timeline events={inspection.timeline} />
      </section>
    </div>
  )
}
