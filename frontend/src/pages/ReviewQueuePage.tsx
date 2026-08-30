import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Clock3, Filter, Search, ShieldAlert, UserRound } from 'lucide-react'
import { useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useI18n } from '../hooks/useI18n'
import { routeLabel } from '../i18n'
import type { ReviewTask } from '../types'
import { formatDateTime, formatScore } from '../utils'

type QueueFilter = 'ALL' | 'HELD' | 'UNASSIGNED'

export function ReviewQueuePage() {
  const [, navigate] = useLocation(); const { t, language } = useI18n()
  const [tasks, setTasks] = useState<ReviewTask[] | null>(null); const [error, setError] = useState<unknown>(null); const [filter, setFilter] = useState<QueueFilter>('ALL'); const [query, setQuery] = useState('')
  const load = useCallback(async () => { try { setError(null); setTasks(await visionQcApi.listReviews()) } catch (caught) { setError(caught) } }, [])
  useEffect(() => { void load() }, [load])
  const visible = useMemo(() => (tasks ?? []).filter((task) => { const matchesFilter = filter === 'ALL' || (filter === 'HELD' ? task.held : !task.assignee); const haystack = `${task.id} ${task.inspectionId} ${task.batchNo} ${task.productCode}`.toLowerCase(); return matchesFilter && haystack.includes(query.toLowerCase()) }), [filter, query, tasks])
  return <div className="page reviews-page"><div className="page-heading"><div><span className="page-kicker">{t('reviews.kicker')}</span><h1>{t('reviews.title')}</h1><p>{t('reviews.subtitle')}</p></div>{tasks && <div className="queue-metrics"><div><span>{t('reviews.title')}</span><strong>{tasks.length}</strong></div><div><span>{t('reviews.held')}</span><strong>{tasks.filter((task) => task.held).length}</strong></div><div><span>{language === 'zh' ? '高优先级' : 'Critical'}</span><strong>{tasks.filter((task) => task.priority === 'CRITICAL').length}</strong></div></div>}</div>
    <div className="queue-toolbar panel"><label className="search-field"><Search size={16} /><input aria-label={language === 'zh' ? '搜索复核任务' : 'Search review tasks'} placeholder={t('reviews.search')} value={query} onChange={(event) => setQuery(event.target.value)} /></label><div className="queue-filters" aria-label={language === 'zh' ? '复核任务筛选' : 'Review filters'}><Filter size={15} />{([['ALL', t('reviews.all')], ['HELD', t('reviews.held')], ['UNASSIGNED', t('reviews.unassigned')]] as const).map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>)}</div><span className="queue-sort">{t('reviews.sort')}</span></div>
    {error ? <ErrorState error={error} onRetry={load} /> : !tasks ? <LoadingState label={language === 'zh' ? '正在读取复核任务…' : 'Loading review tasks…'} /> : <div className="review-table panel"><div className="review-table-head"><span>{language === 'zh' ? '图片 / 批次' : 'Image / batch'}</span><span>{t('reviews.route')}</span><span>{t('reviews.status')}</span><span>{t('reviews.owner')}</span><span>{t('reviews.action')}</span></div>{visible.map((task) => <article key={task.id} className={task.route === 'SAFE_DEGRADE' ? 'safe-degrade-row' : ''}><div className="task-identity"><img src={task.thumbnailUrl} alt="" /><span><strong>{task.batchNo}</strong><small>{task.id}</small><code>{task.inspectionId}</code></span></div><div className="route-cell">{task.route === 'SAFE_DEGRADE' ? <ShieldAlert size={17} /> : task.held ? <AlertTriangle size={17} /> : <span className="route-dot" />}<span><strong>{routeLabel(language, task.route)}</strong><small>{task.held ? (language === 'zh' ? '批次流转已暂停' : 'Batch flow is paused') : (language === 'zh' ? '未执行外部质量写操作' : 'No external quality write')}</small></span></div><div className="risk-cell"><StatusBadge status={task.held ? 'BATCH_HELD' : 'REVIEW_REQUIRED'} size="sm" /><strong>{formatScore(task.score)}</strong><small>{t('inspection.score')}</small></div><div className="owner-cell"><span><UserRound size={15} />{task.assignee ?? t('reviews.unassigned')}</span><span className={task.route === 'SAFE_DEGRADE' ? 'overdue' : ''}><Clock3 size={15} />{formatDateTime(task.slaAt, false, language)}</span></div><button className="row-action" onClick={() => navigate(`/reviews/${task.id}`)}>{task.assignee ? t('reviews.open') : t('reviews.claim')}<ArrowRight size={16} /></button></article>)}{visible.length === 0 && <div className="empty-row">{t('reviews.empty')}</div>}</div>}
    <div className="queue-footnote"><ShieldAlert size={17} /><span><strong>{t('reviews.safety')}{language === 'zh' ? '：' : ': '}</strong>{t('reviews.safetyBody')}</span></div>
  </div>
}
