import { useCallback, useEffect, useState } from 'react'
import { Activity, ArrowRight, ClipboardCheck, FileWarning, RefreshCw, Server, ShieldAlert, UploadCloud } from 'lucide-react'
import { Link, useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useDeploymentContext } from '../components/AppShell'
import type { GatewayStatus, Inspection, OperationsSummary, ReviewTask } from '../types'
import { formatDateTime, formatScore } from '../utils'

const routeLabels: Record<string, string> = {
  AUTO_RELEASE: '策略自动放行',
  MANUAL_REVIEW: '等待人工复核',
  BATCH_HOLD_AND_REVIEW: '批次暂扣复核',
  SAFE_REVIEW: '安全降级',
  PENDING: '等待模型结果',
}

function openIncidentCount(summary: OperationsSummary) {
  return Object.entries(summary.incidentCounts)
    .filter(([status]) => status !== 'CLOSED')
    .reduce((total, [, count]) => total + count, 0)
}

export function OverviewPage() {
  const [, navigate] = useLocation()
  const { context } = useDeploymentContext()
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [recent, setRecent] = useState<Inspection[] | null>(null)
  const [reviews, setReviews] = useState<ReviewTask[] | null>(null)
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const [nextSummary, nextRecent, nextReviews, nextGateways] = await Promise.all([
        visionQcApi.getOperationsSummary(),
        visionQcApi.listRecentInspections(),
        visionQcApi.listReviews(),
        visionQcApi.listGatewayStatuses(),
      ])
      setSummary(nextSummary)
      setRecent(nextRecent)
      setReviews(nextReviews)
      setGateways(nextGateways)
    } catch (caught) {
      setError(caught)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!summary || !recent || !reviews || !gateways) return <div className="page"><LoadingState label="正在汇总运营数据…" /></div>

  const incidentCount = openIncidentCount(summary)
  const onlineRate = summary.gatewayOnlineRate === undefined ? '—' : `${Math.round(summary.gatewayOnlineRate * 100)}%`
  const attention = reviews.slice(0, 4)
  const routeTotal = Object.values(summary.routeCounts).reduce((total, count) => total + count, 0)

  return (
    <div className="page overview-page">
      <div className="page-heading overview-heading">
        <div>
          <span className="page-kicker">运营总览 · API 运行数据</span>
          <h1>今天的质量控制面</h1>
          <p>聚合检测流转、人工责任、质量事件和边缘接入状态。没有记录时显示空状态，不用演示数字填充。</p>
        </div>
        <div className="heading-actions">
          <div className="last-updated"><span>最近刷新</span><strong>{formatDateTime(summary.generatedAt, true)}</strong></div>
          <button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button>
          <Link className="primary-button" href="/upload"><UploadCloud size={16} />手动上传</Link>
        </div>
      </div>

      <div className="overview-context-line">
        <span className="context-pip" aria-hidden="true" />
        <strong>{context?.tenant.name ?? '当前客户'}</strong>
        <span>/</span>
        <code>{context?.currentDeployment?.packKey ?? 'deployment pack 未加载'}</code>
        <span>·</span>
        <span>{context?.currentDeployment?.displayName ?? '等待部署上下文'}</span>
      </div>

      <section className="metric-grid" aria-label="运营指标">
        <article className="metric-card">
          <div className="metric-label"><Activity size={16} />检测吞吐 <span>最近 24 小时</span></div>
          <strong>{summary.inspections24h}</strong>
          <small>API 已接收检测记录</small>
        </article>
        <article className="metric-card">
          <div className="metric-label"><ShieldAlert size={16} />异常路由 <span>策略输出</span></div>
          <strong>{routeTotal}</strong>
          <small>{summary.routeCounts.BATCH_HOLD_AND_REVIEW ?? 0} 个批次暂扣 · {summary.routeCounts.MANUAL_REVIEW ?? 0} 个等待复核</small>
        </article>
        <article className={`metric-card ${summary.reviewBacklog > 0 ? 'metric-warning' : ''}`}>
          <div className="metric-label"><ClipboardCheck size={16} />复核积压 <span>当前租户</span></div>
          <strong>{summary.reviewBacklog}</strong>
          <small>{summary.reviewHighRisk} 个高风险任务需要优先处理</small>
        </article>
        <article className={`metric-card ${incidentCount > 0 ? 'metric-danger' : ''}`}>
          <div className="metric-label"><FileWarning size={16} />事件处理中 <span>未关闭</span></div>
          <strong>{incidentCount}</strong>
          <small>{summary.incidentCounts.VERIFYING ?? 0} 个等待验证 · {summary.incidentCounts.ACTION_PENDING ?? 0} 个待处置</small>
        </article>
        <article className={`metric-card ${summary.gatewayQueueDepth > 0 ? 'metric-warning' : ''}`}>
          <div className="metric-label"><Server size={16} />Gateway 在线率 <span>心跳</span></div>
          <strong>{onlineRate}</strong>
          <small>{summary.gatewayQueueDepth} 个本地待补传 · {summary.gatewaysTotal} 个已注册</small>
        </article>
      </section>

      <div className="overview-layout">
        <section className="work-panel attention-panel">
          <div className="panel-heading compact-heading">
            <div><span className="section-index">01</span><h2>需要操作</h2></div>
            <Link className="text-button" href="/reviews">打开复核队列<ArrowRight size={14} /></Link>
          </div>
          {attention.length === 0 ? (
            <div className="inline-empty"><ClipboardCheck size={19} /><strong>当前没有待处理复核</strong><span>所有已返回的任务均已完成或暂无数据。</span></div>
          ) : (
            <div className="attention-list">
              {attention.map((task) => (
                <button key={task.id} className="attention-row" onClick={() => navigate(`/reviews/${task.id}`)}>
                  <span className={`attention-priority priority-${task.priority.toLowerCase()}`} aria-label={`优先级 ${task.priority}`} />
                  <span className="attention-main"><strong>{task.batchNo}</strong><small>{task.productCode} · {task.station} · {task.id}</small></span>
                  <span className="attention-score"><strong>{formatScore(task.score)}</strong><small>{task.held ? '批次暂扣' : routeLabels[task.route]}</small></span>
                  <StatusBadge status={task.held ? 'BATCH_HELD' : 'REVIEW_REQUIRED'} size="sm" />
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="work-panel flow-panel">
          <div className="panel-heading compact-heading"><div><span className="section-index">02</span><h2>检测流转</h2></div><span className="panel-note">最近 24 小时</span></div>
          {routeTotal === 0 ? <div className="inline-empty"><Activity size={19} /><strong>暂无检测路由</strong><span>接入第一条检测后，这里会显示策略流向。</span></div> : (
            <div className="route-list">
              {Object.entries(summary.routeCounts).sort(([, a], [, b]) => b - a).map(([route, count]) => (
                <div className="route-row" key={route}><span>{routeLabels[route] ?? route}</span><div className="route-bar"><i style={{ width: `${Math.max((count / routeTotal) * 100, 3)}%` }} /></div><strong>{count}</strong></div>
              ))}
            </div>
          )}
          <div className="boundary-note"><ShieldAlert size={15} /><span>异常路由只表示模型/策略状态，不等于已确认缺陷。</span></div>
        </section>

        <section className="work-panel gateway-summary-panel">
          <div className="panel-heading compact-heading"><div><span className="section-index">03</span><h2>现场接入</h2></div><Link className="text-button" href="/operations">查看 Gateway<ArrowRight size={14} /></Link></div>
          {gateways.length === 0 ? (
            <div className="inline-empty"><Server size={19} /><strong>没有 Gateway 心跳</strong><span>当前租户尚未报告在线边缘节点。</span></div>
          ) : (
            <div className="gateway-mini-list">
              {gateways.slice(0, 3).map((gateway) => (
                <div className="gateway-mini-row" key={gateway.gatewayId}><span className={`status-dot ${gateway.status.toLowerCase()}`} /><span><strong>{gateway.stationCode}</strong><small>{gateway.gatewayId} · {formatDateTime(gateway.lastHeartbeatAt, true)}</small></span><span className="gateway-mini-queue"><b>{gateway.queueDepth}</b><small>队列</small></span><StatusBadge status={gateway.status} size="sm" /></div>
              ))}
            </div>
          )}
          <div className="gateway-rollup"><span>成功上传 <strong>{summary.uploadSuccessCount}</strong></span><span>失败 / 重试 <strong className={summary.uploadFailureCount ? 'danger-text' : ''}>{summary.uploadFailureCount}</strong></span></div>
        </section>

        <section className="work-panel recent-ops-panel">
          <div className="panel-heading compact-heading"><div><span className="section-index">04</span><h2>最近检测</h2></div><span className="panel-note">API 返回 {recent.length} 条</span></div>
          {recent.length === 0 ? <div className="inline-empty"><Activity size={19} /><strong>暂无检测记录</strong><span>可以从手动上传或 Edge Gateway 接入第一张图片。</span><Link className="text-button" href="/upload">去上传<ArrowRight size={14} /></Link></div> : (
            <div className="recent-ops-list">
              {recent.slice(0, 5).map((inspection) => (
                <Link key={inspection.id} href={`/inspections/${inspection.id}`} className="recent-ops-row"><span><strong>{inspection.context.batchNo}</strong><small>{inspection.id} · {formatDateTime(inspection.updatedAt, true)}</small></span><span>{inspection.context.productCode} · {inspection.context.station}</span><StatusBadge status={inspection.status} size="sm" /><ArrowRight size={14} /></Link>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="demo-disclosure"><span className="disclosure-label">数据边界</span><span>当前环境允许 Mock MES / QMS 和模拟图像；本页指标由 API 返回，不能外推为真实产线效果。</span><Link href="/modelops">查看 ModelOps 证据边界<ArrowRight size={14} /></Link></div>
    </div>
  )
}
