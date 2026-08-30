import { useCallback, useEffect, useState } from 'react'
import { Activity, ArrowRight, ClipboardCheck, Eye, FileWarning, RefreshCw, Server, ShieldAlert, UploadCloud, UserRoundCheck } from 'lucide-react'
import { Link, useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useDeploymentContext } from '../components/AppShell'
import { useI18n } from '../hooks/useI18n'
import { useTenantConfig, localized } from '../config/tenant'
import type { GatewayStatus, Inspection, OperationsSummary, ReviewTask } from '../types'
import { routeLabel } from '../i18n'
import { formatDateTime, formatScore, formatStation } from '../utils'

function openIncidentCount(summary: OperationsSummary) {
  return Object.entries(summary.incidentCounts).filter(([status]) => status !== 'CLOSED').reduce((total, [, count]) => total + count, 0)
}

export function OverviewPage() {
  const [, navigate] = useLocation()
  const { context } = useDeploymentContext()
  const { t, language } = useI18n()
  const { config, industryPack } = useTenantConfig()
  const [summary, setSummary] = useState<OperationsSummary | null>(null)
  const [recent, setRecent] = useState<Inspection[] | null>(null)
  const [reviews, setReviews] = useState<ReviewTask[] | null>(null)
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const [nextSummary, nextRecent, nextReviews, nextGateways] = await Promise.all([visionQcApi.getOperationsSummary(), visionQcApi.listRecentInspections(), visionQcApi.listReviews(), visionQcApi.listGatewayStatuses()])
      setSummary(nextSummary); setRecent(nextRecent); setReviews(nextReviews); setGateways(nextGateways)
    } catch (caught) { setError(caught) }
  }, [])
  useEffect(() => { void load() }, [load])
  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!summary || !recent || !reviews || !gateways) return <div className="page"><LoadingState label={language === 'zh' ? '正在汇总运营数据…' : 'Summarizing operations…'} /></div>

  const incidentCount = openIncidentCount(summary)
  const onlineRate = summary.gatewayOnlineRate === undefined ? '—' : `${Math.round(summary.gatewayOnlineRate * 100)}%`
  const attention = reviews.slice(0, 4)
  const routeTotal = Object.values(summary.routeCounts).reduce((total, count) => total + count, 0)
  return <div className="page overview-page">
    <div className="page-heading overview-heading"><div><span className="page-kicker">{t('overview.kicker')}</span><h1>{t('overview.title')}</h1><p>{t('overview.subtitle')}</p></div><div className="heading-actions"><div className="last-updated"><span>{t('overview.lastRefresh')}</span><strong>{formatDateTime(summary.generatedAt, true, language)}</strong></div><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />{t('common.refresh')}</button><Link className="primary-button" href="/upload"><UploadCloud size={16} />{t('overview.upload')}</Link></div></div>

    <div className="overview-context-line"><span className="context-pip" /><strong>{config.branding.displayName}</strong><span>·</span><span>{localized(industryPack.name, language)}</span><span>·</span><code>{context?.currentDeployment?.packKey ?? 'tenant-config.v1'}</code></div>

    <section className="setup-banner" aria-labelledby="setup-banner-title"><div className="setup-art"><span>VQ</span><i /><i /><i /></div><div className="setup-copy"><span className="eyebrow">{t('overview.setupPrompt')}</span><h2 id="setup-banner-title">{config.setupComplete ? (language === 'zh' ? '你的工作台已准备好' : 'Your workspace is ready') : t('overview.setupPrompt')}</h2><p>{t('overview.setupPromptBody')}</p></div><ol className="setup-steps"><li><b>01</b><span>{t('overview.stepIndustry')}</span></li><li><b>02</b><span>{t('overview.stepBrand')}</span></li><li><b>03</b><span>{t('overview.stepSource')}</span></li><li><b>04</b><span>{t('overview.stepReview')}</span></li></ol><div className="setup-actions"><Link className="primary-button" href="/start">{config.setupComplete ? t('nav.setup') : t('overview.setupAction')}<ArrowRight size={16} /></Link><Link className="secondary-button" href="/upload">{t('overview.tryExample')}</Link></div></section>

    <section className="metric-grid" aria-label={language === 'zh' ? '运营指标' : 'Operations metrics'}><article className="metric-card"><div className="metric-label"><Activity size={16} />{t('overview.received')}<span>{t('overview.receivedHint')}</span></div><strong>{summary.inspections24h}</strong><small>{language === 'zh' ? '系统已接收并保存的检测图片' : 'Inspections received and saved'}</small></article><article className={`metric-card ${summary.reviewBacklog > 0 ? 'metric-warning' : ''}`}><div className="metric-label"><ClipboardCheck size={16} />{t('overview.reviewBacklog')}<span>{t('overview.reviewBacklogHint')}</span></div><strong>{summary.reviewBacklog}</strong><small>{summary.reviewHighRisk} · {language === 'zh' ? '高风险任务优先处理' : 'high-risk tasks first'}</small></article><article className={`metric-card ${incidentCount > 0 ? 'metric-danger' : ''}`}><div className="metric-label"><FileWarning size={16} />{t('overview.incidents')}<span>{t('overview.incidentsHint')}</span></div><strong>{incidentCount}</strong><small>{summary.incidentCounts.VERIFYING ?? 0} · {language === 'zh' ? '等待验证' : 'awaiting verification'}</small></article><article className={`metric-card ${summary.gatewayQueueDepth > 0 ? 'metric-warning' : ''}`}><div className="metric-label"><Server size={16} />{t('overview.gateway')}<span>{t('overview.gatewayHint')}</span></div><strong>{onlineRate}</strong><small>{summary.gatewayQueueDepth} · {language === 'zh' ? '张图片等待补传' : 'images queued'}</small></article></section>

    <div className="overview-layout">
      <section className="work-panel attention-panel"><div className="panel-heading"><div><UserRoundCheck size={18} /><span className="eyebrow">01</span><h2>{t('overview.attention')}</h2></div><Link className="text-button" href="/reviews">{t('overview.openQueue')}<ArrowRight size={14} /></Link></div>{attention.length === 0 ? <div className="inline-empty"><ClipboardCheck size={19} /><strong>{t('overview.emptyReview')}</strong><span>{t('overview.emptyReviewBody')}</span></div> : <div className="attention-list">{attention.map((task) => <button key={task.id} className="attention-row" onClick={() => navigate(`/reviews/${task.id}`)}><span className={`attention-priority priority-${task.priority.toLowerCase()}`} /><span className="attention-main"><strong>{task.batchNo}</strong><small>{task.productCode} · {formatStation(task.station, language)} · {task.id}</small></span><span className="attention-score"><strong>{formatScore(task.score)}</strong><small>{task.held ? t('status.BATCH_HELD') : routeLabel(language, task.route)}</small></span><StatusBadge status={task.held ? 'BATCH_HELD' : 'REVIEW_REQUIRED'} size="sm" /><ArrowRight size={15} /></button>)}</div>}</section>

      <section className="work-panel flow-panel"><div className="panel-heading"><div><Eye size={18} /><span className="eyebrow">02</span><h2>{t('overview.route')}</h2></div><span className="panel-note">{t('overview.routeHint')}</span></div>{routeTotal === 0 ? <div className="inline-empty"><Activity size={19} /><strong>{t('common.noData')}</strong><span>{t('overview.routeBoundary')}</span></div> : <div className="route-list">{Object.entries(summary.routeCounts).sort(([, a], [, b]) => b - a).map(([route, count]) => <div className="route-row" key={route}><span>{routeLabel(language, route)}</span><div className="route-bar"><i style={{ width: `${Math.max((count / routeTotal) * 100, 3)}%` }} /></div><strong>{count}</strong></div>)}</div>}<div className="boundary-note"><ShieldAlert size={15} /><span>{t('overview.routeBoundary')}</span></div></section>

      <section className="work-panel gateway-summary-panel"><div className="panel-heading"><div><Server size={18} /><span className="eyebrow">03</span><h2>{t('overview.gatewayPanel')}</h2></div><Link className="text-button" href="/operations">{t('common.viewDetails')}<ArrowRight size={14} /></Link></div>{gateways.length === 0 ? <div className="inline-empty"><Server size={19} /><strong>{t('gateway.empty')}</strong><span>{t('gateway.emptyBody')}</span></div> : <div className="gateway-mini-list">{gateways.slice(0, 3).map((gateway) => <div className="gateway-mini-row" key={gateway.gatewayId}><span className={`status-dot ${gateway.status.toLowerCase()}`} /><span><strong>{formatStation(gateway.stationCode, language)}</strong><small>{gateway.gatewayId} · {formatDateTime(gateway.lastHeartbeatAt, true, language)}</small></span><span className="gateway-mini-queue"><b>{gateway.queueDepth}</b><small>{t('overview.gatewayHint')}</small></span><StatusBadge status={gateway.status} size="sm" /></div>)}</div>}<div className="gateway-rollup"><span>{language === 'zh' ? '成功上传' : 'Uploaded'} <strong>{summary.uploadSuccessCount}</strong></span><span>{language === 'zh' ? '失败 / 重试' : 'Failed / retry'} <strong className={summary.uploadFailureCount ? 'danger-text' : ''}>{summary.uploadFailureCount}</strong></span></div></section>

      <section className="work-panel recent-ops-panel"><div className="panel-heading"><div><Activity size={18} /><span className="eyebrow">04</span><h2>{t('overview.recent')}</h2></div><span className="panel-note">{recent.length}</span></div>{recent.length === 0 ? <div className="inline-empty"><Activity size={19} /><strong>{t('overview.recentEmpty')}</strong><span>{t('overview.recentEmptyBody')}</span><Link className="text-button" href="/upload">{t('overview.upload')}<ArrowRight size={14} /></Link></div> : <div className="recent-ops-list">{recent.slice(0, 5).map((inspection) => <Link key={inspection.id} href={`/inspections/${inspection.id}`} className="recent-ops-row"><span><strong>{inspection.context.batchNo}</strong><small>{inspection.id} · {formatDateTime(inspection.updatedAt, true, language)}</small></span><span>{inspection.context.productCode} · {formatStation(inspection.context.station, language)}</span><StatusBadge status={inspection.status} size="sm" /><ArrowRight size={14} /></Link>)}</div>}</section>
    </div>

    <div className="demo-disclosure"><span className="disclosure-label">{t('overview.demoData')}</span><span>{t('overview.demoDataBody')}</span><Link aria-label={language === 'zh' ? `查看${t('nav.modelops')}` : `View ${t('nav.modelops')}`} href="/modelops">{t('nav.modelops')}<ArrowRight size={14} /></Link><Link className="demo-start-link" href="/upload?demo=1">{t('overview.useExample')}<ArrowRight size={14} /></Link></div>
  </div>
}
