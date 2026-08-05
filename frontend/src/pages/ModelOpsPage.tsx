import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, FileCheck2, GitBranch, RefreshCw, ShieldAlert } from 'lucide-react'
import { Link } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { useDeploymentContext } from '../components/AppShell'
import type { ModelOpsStatus } from '../types'
import { formatDateTime } from '../utils'

function EvidenceState({ ok, label, detail, warning = false }: { ok: boolean; label: string; detail: string; warning?: boolean }) {
  return <div className={`evidence-state ${ok ? 'evidence-ok' : warning ? 'evidence-warning' : 'evidence-danger'}`}><span className="evidence-icon">{ok ? <CheckCircle2 size={17} /> : warning ? <AlertTriangle size={17} /> : <CircleDashed size={17} />}</span><span><strong>{label}</strong><small>{detail}</small></span></div>
}

export function ModelOpsPage() {
  const { context } = useDeploymentContext()
  const [status, setStatus] = useState<ModelOpsStatus | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(async () => {
    try { setError(null); setStatus(await visionQcApi.getModelOpsStatus()) } catch (caught) { setError(caught) }
  }, [])
  useEffect(() => { void load() }, [load, context?.tenant.id])

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!status) return <div className="page"><LoadingState label="正在读取 Deployment Pack 与 ModelOps 证据…" /></div>

  const deployment = context?.currentDeployment
  const gateChecks = (status.gateResults as { checks?: Record<string, { status?: string; value?: unknown; threshold?: unknown }> }).checks ?? {}
  const qualificationLabel = status.reportStatus
  const sourceLabel = status.datasetSourceType === 'DEMO_SYNTHETIC'
    ? 'DEMO_SYNTHETIC · 演示数据'
    : status.datasetSourceType === 'OFFICIAL_BENCHMARK'
      ? 'OFFICIAL_BENCHMARK · MVTec AD'
      : 'CUSTOMER_PILOT · 客户数据'
  const releaseLabel = status.reportStatus === 'BENCHMARK_PASS'
    ? '公开基准测试通过，但还需要真实客户数据'
    : status.reportStatus === 'CUSTOMER_PILOT_PASS'
      ? '客户试点证据通过，可以申请人工批准'
      : '证据不足或安全门槛未通过，不能上线'
  return (
    <div className="page modelops-page">
      <div className="page-heading">
        <div><span className="page-kicker">模型证据 · 供技术与审核人员查看</span><h1>这个模型现在能上线吗？</h1><p>这里把答案和原因放在一起。即使演示流程能运行，也不代表模型已经达到真实工厂上线标准。</p></div>
        <button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />重新检查证据</button>
      </div>

      <div className="governance-context"><span>当前客户</span><strong>{context?.tenant.name ?? status.tenantId}</strong><span>/</span><code>{status.packKey}</code><span>/</span><strong>{status.productCode}</strong><span className="context-status">Deployment Pack {status.deploymentStatus}</span></div>

      <div className="governance-top-grid">
        <section className="work-panel model-identity-panel">
          <div className="panel-heading compact-heading"><div><FileCheck2 size={18} /><h2>当前使用的模型</h2></div></div>
          <dl className="governance-dl">
            <div><dt>模型</dt><dd><strong>{status.modelId}</strong><small>{status.modelVersion}</small></dd></div>
            <div><dt>特征库</dt><dd><code>{status.featureBankVersion}</code></dd></div>
            <div><dt>Deployment Pack</dt><dd><code>{status.packKey}@{status.deploymentVersion}</code></dd></div>
            <div><dt>包完整性</dt><dd><span className="inline-status success"><CheckCircle2 size={14} />{status.packageVerified ? 'manifest SHA 已登记' : '未登记 SHA'}</span></dd></div>
          </dl>
          <div className="model-identity-foot"><GitBranch size={15} /><span>当前运行时允许路由；ModelOps 发布状态仍由独立证据门禁控制。</span></div>
        </section>

        <section className="work-panel release-gate-panel">
          <div className="panel-heading compact-heading"><div><ShieldAlert size={19} /><h2>上线结论</h2></div></div>
          <div className="release-gate-state"><span className="release-gate-mark"><ShieldAlert size={25} /></span><span><strong>{releaseLabel}</strong><small>报告状态：{qualificationLabel} · 生命周期：{status.modelReleaseStatus}</small></span></div>
          <div className="release-reasons"><span><b>Deployment Pack</b>{status.deploymentStatus}</span><span><b>数据来源</b>{sourceLabel}</span><span><b>来源状态</b>{status.datasetSourceStatus ?? '未登记'}</span><span><b>客户数据 Gate</b>{status.customerDataGate}</span></div>
          <button className="secondary-button" disabled={!status.activationAllowed} title={status.activationAllowed ? '仍需具名审批后启用' : '必须先补齐客户数据来源、测试门槛和人工审批'}>{status.activationAllowed ? '申请启用模型' : '当前不能启用'}</button>
        </section>
      </div>

      <section className="work-panel evidence-panel">
        <div className="panel-heading compact-heading"><div><CheckCircle2 size={18} /><h2>为什么得出这个结论</h2></div><span className="panel-note">报告更新 {formatDateTime(status.reportGeneratedAt, true)}</span></div>
        <div className="evidence-grid">
          <EvidenceState ok={status.datasetSourceType === 'DEMO_SYNTHETIC'} warning={status.datasetSourceType === 'DEMO_SYNTHETIC'} label="DEMO_SYNTHETIC" detail="内置演示数据，仅证明页面与闭环可运行，不得用于效果声明" />
          <EvidenceState ok={status.mvtecMetricsAvailable} label="OFFICIAL_BENCHMARK" detail={status.mvtecMetricsAvailable ? 'MVTec benchmark 证据可用，不代表工厂/客户现场效果' : '可选导入；当前没有 benchmark 证据'} />
          <EvidenceState ok={status.calibrationConstraintsSatisfied} label="阈值校准约束" detail={status.calibrationConstraintsSatisfied ? '满足发布约束' : '当前 smoke 约束未满足'} />
          <EvidenceState ok={status.customerDataGate === 'PASS'} label="CUSTOMER_PILOT provenance" detail={status.customerDataGate === 'PASS' ? '客户数据 provenance 已验证' : '缺少客户数据 provenance，Pilot approval 被阻断'} />
        </div>
        <div className="release-reasons" aria-label="Pilot 门槛逐项结果">
          {Object.entries(gateChecks).map(([name, gate]) => <span key={name}><b>{name}</b>{gate.status ?? 'INSUFFICIENT_EVIDENCE'}{gate.value !== undefined && gate.value !== null ? ` · ${String(gate.value)}` : ''}</span>)}
        </div>
        <div className="evidence-boundary"><AlertTriangle size={16} /><strong>重要边界：</strong><span>{status.datasetSourceType === 'DEMO_SYNTHETIC' ? '演示数据只证明系统及评测流程可以启动，不是效果证据。' : 'benchmark 结果只证明系统及评测流程可运行，不代表任何工厂现场效果；客户数据必须通过受控导入和 provenance gate。'}</span></div>
          <p className="source-line">证据来源：<code>{status.evidenceSource}</code>{status.evidencePackageSha256 ? <> · 证据摘要 <code>{status.evidencePackageSha256}</code></> : null}</p>
      </section>

      <div className="governance-two-col">
        <section className="work-panel threshold-panel">
          <div className="panel-heading compact-heading"><div><GitBranch size={18} /><h2>分数如何决定下一步</h2></div><span className="panel-note">来自当前产品配置</span></div>
          {deployment ? <>
            <table className="threshold-table"><thead><tr><th>范围</th><th>复核阈值</th><th>暂扣阈值</th></tr></thead><tbody><tr><td>默认</td><td>{deployment.policy.default.reviewThreshold.toFixed(2)}</td><td>{deployment.policy.default.holdThreshold.toFixed(2)}</td></tr>{deployment.policy.overrides.map((override, index) => <tr key={`${override.productCode}-${override.stationCode}-${index}`}><td>{override.productCode ?? '所有产品'} · {override.stationCode ?? '所有工位'}</td><td>{override.reviewThreshold.toFixed(2)}</td><td>{override.holdThreshold.toFixed(2)}</td></tr>)}</tbody></table>
            <p className="table-note">阈值只负责安全路由。触发复核或暂扣不会自动确认缺陷。</p>
          </> : <div className="inline-empty"><CircleDashed size={18} /><strong>当前部署包不可用</strong><span>无法显示策略阈值。</span></div>}
        </section>

        <section className="work-panel limits-panel">
          <div className="panel-heading compact-heading"><div><AlertTriangle size={18} /><h2>还缺什么</h2></div><span className="panel-note">建议下一步</span></div>
          <ul className="limits-list">{status.limitations.map((item) => <li key={item}><AlertTriangle size={15} /><span>{item}</span></li>)}</ul>
          <div className="recommendation-box"><strong>建议</strong><ul>{status.releaseRecommendation.map((item) => <li key={item}>{item}</li>)}</ul></div>
        </section>
      </div>

      <div className="demo-disclosure"><span className="disclosure-label">数据来源状态</span><span>{sourceLabel} · {status.datasetSourceStatus ?? '未登记'} · {status.reportStatus} · {status.riskLabels.join(' / ') || '无风险标签'}。Fingerprint：<code>{status.datasetFingerprint ?? '—'}</code>。数据集导入通过受控 API/CLI 完成，原始数据不进入 Git 或前端静态目录。</span><Link href="/operations">查看 Gateway 绑定<ArrowRight size={14} /></Link></div>
    </div>
  )
}
