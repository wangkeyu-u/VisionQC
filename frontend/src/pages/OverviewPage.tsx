import { useCallback, useEffect, useState } from 'react'
import { Activity, ArrowRight, ClipboardCheck, Eye, FileWarning, ImagePlus, RefreshCw, Server, ShieldAlert, UploadCloud, UserRoundCheck } from 'lucide-react'
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
          <span className="page-kicker">工作首页</span>
          <h1>质量工作台</h1>
          <p>从这里开始：先处理等待人工确认的图片，再跟进尚未关闭的质量问题。</p>
        </div>
        <div className="heading-actions">
          <div className="last-updated"><span>最近刷新</span><strong>{formatDateTime(summary.generatedAt, true)}</strong></div>
          <button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button>
          <Link className="primary-button" href="/upload"><UploadCloud size={16} />上传图片</Link>
        </div>
      </div>

      <div className="overview-context-line">
        <span className="context-pip" aria-hidden="true" />
        <strong>{context?.tenant.name ?? '当前客户'}</strong>
        <span>· 当前产品配置</span>
        <strong>{context?.currentDeployment?.displayName ?? '正在读取…'}</strong>
        <details><summary>技术编号</summary><code>{context?.currentDeployment?.packKey ?? '配置编号未加载'}</code></details>
      </div>

      <section className="starter-panel" aria-labelledby="starter-title">
        <div className="starter-intro">
          <span className="starter-mark"><ImagePlus size={23} /></span>
          <div><strong id="starter-title">第一次使用？三分钟完成一次演示</strong><p>没有真实工厂图片也可以开始。系统会自动准备演示图片和必填信息。</p></div>
        </div>
        <ol className="starter-steps">
          <li><span>1</span><div><strong>载入图片</strong><small>使用内置工业演示样本</small></div></li>
          <li><span>2</span><div><strong>查看可疑区域</strong><small>对照原图、热力图和分数</small></div></li>
          <li><span>3</span><div><strong>人工确认</strong><small>留下结论和可追溯原因</small></div></li>
        </ol>
        <Link className="primary-button starter-action" href="/upload?demo=1">使用演示图片开始<ArrowRight size={17} /></Link>
      </section>

      <section className="metric-grid" aria-label="运营指标">
        <article className="metric-card">
          <div className="metric-label"><Activity size={16} />今天收到的图片 <span>最近 24 小时</span></div>
          <strong>{summary.inspections24h}</strong>
          <small>系统已经接收并保存的检测图片</small>
        </article>
        <article className={`metric-card ${summary.reviewBacklog > 0 ? 'metric-warning' : ''}`}>
          <div className="metric-label"><ClipboardCheck size={16} />等待人工确认 <span>当前工厂</span></div>
          <strong>{summary.reviewBacklog}</strong>
          <small>{summary.reviewHighRisk} 个高风险任务需要优先查看</small>
        </article>
        <article className={`metric-card ${incidentCount > 0 ? 'metric-danger' : ''}`}>
          <div className="metric-label"><FileWarning size={16} />质量问题处理中 <span>尚未关闭</span></div>
          <strong>{incidentCount}</strong>
          <small>{summary.incidentCounts.VERIFYING ?? 0} 个等待验证 · {summary.incidentCounts.ACTION_PENDING ?? 0} 个待处置</small>
        </article>
        <article className={`metric-card ${summary.gatewayQueueDepth > 0 ? 'metric-warning' : ''}`}>
          <div className="metric-label"><Server size={16} />现场设备在线 <span>实时连接</span></div>
          <strong>{onlineRate}</strong>
          <small>{summary.gatewayQueueDepth} 张图片等待补传 · {summary.gatewaysTotal} 个接入程序</small>
        </article>
      </section>

      <div className="overview-layout">
        <section className="work-panel attention-panel">
          <div className="panel-heading compact-heading">
            <div><UserRoundCheck size={18} /><h2>现在需要你处理</h2></div>
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
          <div className="panel-heading compact-heading"><div><Eye size={18} /><h2>图片处理去向</h2></div><span className="panel-note">最近 24 小时</span></div>
          {routeTotal === 0 ? <div className="inline-empty"><Activity size={19} /><strong>暂无检测路由</strong><span>接入第一条检测后，这里会显示策略流向。</span></div> : (
            <div className="route-list">
              {Object.entries(summary.routeCounts).sort(([, a], [, b]) => b - a).map(([route, count]) => (
                <div className="route-row" key={route}><span>{routeLabels[route] ?? route}</span><div className="route-bar"><i style={{ width: `${Math.max((count / routeTotal) * 100, 3)}%` }} /></div><strong>{count}</strong></div>
              ))}
            </div>
          )}
          <div className="boundary-note"><ShieldAlert size={15} /><span>这里显示系统把图片送到了哪里，不代表已经确认产品有缺陷。</span></div>
        </section>

        <section className="work-panel gateway-summary-panel">
          <div className="panel-heading compact-heading"><div><Server size={18} /><h2>现场设备连接</h2></div><Link className="text-button" href="/operations">查看详情<ArrowRight size={14} /></Link></div>
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
          <div className="panel-heading compact-heading"><div><Activity size={18} /><h2>最近处理的图片</h2></div><span className="panel-note">共 {recent.length} 条</span></div>
          {recent.length === 0 ? <div className="inline-empty"><Activity size={19} /><strong>暂无检测记录</strong><span>可以从手动上传或 Edge Gateway 接入第一张图片。</span><Link className="text-button" href="/upload">去上传<ArrowRight size={14} /></Link></div> : (
            <div className="recent-ops-list">
              {recent.slice(0, 5).map((inspection) => (
                <Link key={inspection.id} href={`/inspections/${inspection.id}`} className="recent-ops-row"><span><strong>{inspection.context.batchNo}</strong><small>{inspection.id} · {formatDateTime(inspection.updatedAt, true)}</small></span><span>{inspection.context.productCode} · {inspection.context.station}</span><StatusBadge status={inspection.status} size="sm" /><ArrowRight size={14} /></Link>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="demo-disclosure"><span className="disclosure-label">演示数据说明</span><span>当前图片、生产系统和质量系统包含模拟数据；页面数字只用于展示流程，不能当作真实工厂效果。</span><Link href="/modelops">查看模型证据<ArrowRight size={14} /></Link></div>
    </div>
  )
}
