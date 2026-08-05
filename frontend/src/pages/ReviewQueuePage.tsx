import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'wouter'
import { AlertTriangle, ArrowRight, Clock3, Filter, Search, ShieldAlert, UserRound } from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import type { ReviewTask } from '../types'
import { formatDateTime, formatScore } from '../utils'

const routeLabels = {
  GREY_ZONE: '分数处于待确认区间',
  HIGH_SCORE_HOLD: '分数较高，批次已暂扣',
  SAFE_DEGRADE: '系统异常，转人工确认',
}

export function ReviewQueuePage() {
  const [, navigate] = useLocation()
  const [tasks, setTasks] = useState<ReviewTask[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [filter, setFilter] = useState<'ALL' | 'HELD' | 'UNASSIGNED'>('ALL')
  const [query, setQuery] = useState('')

  const load = useCallback(async () => {
    try { setError(null); setTasks(await visionQcApi.listReviews()) } catch (caught) { setError(caught) }
  }, [])
  useEffect(() => { void load() }, [load])

  const visible = useMemo(() => (tasks ?? []).filter((task) => {
    const matchesFilter = filter === 'ALL' || (filter === 'HELD' ? task.held : !task.assignee)
    const haystack = `${task.id} ${task.inspectionId} ${task.batchNo} ${task.productCode}`.toLowerCase()
    return matchesFilter && haystack.includes(query.toLowerCase())
  }), [filter, query, tasks])

  return (
    <div className="page reviews-page">
      <div className="page-heading">
        <div><span className="page-kicker">人工确认</span><h1>等待我确认的图片</h1><p>从最需要关注的任务开始。系统会提供图片和可疑区域，最终判断由你根据现场标准作出。</p></div>
        <div className="queue-metrics"><div><span>等待确认</span><strong>{tasks?.length ?? '—'}</strong></div><div><span>批次已暂扣</span><strong>{tasks ? tasks.filter((task) => task.held).length : '—'}</strong></div><div><span>即将超时</span><strong>{tasks ? tasks.filter((task) => task.priority === 'CRITICAL').length : '—'}</strong></div></div>
      </div>

      <div className="queue-toolbar panel">
        <label className="search-field"><Search size={16} /><input aria-label="搜索复核任务" placeholder="搜索任务、检测或批次…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="queue-filters" aria-label="复核任务筛选">
          <Filter size={15} />
          {([['ALL', '全部'], ['HELD', '已暂扣'], ['UNASSIGNED', '待认领']] as const).map(([value, label]) => (
            <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
        <span className="queue-sort">排序：先看风险高、等待久的任务</span>
      </div>

      {error ? <ErrorState error={error} onRetry={load} /> : !tasks ? <LoadingState label="正在读取复核任务…" /> : (
        <div className="review-table panel">
          <div className="review-table-head"><span>图片 / 批次</span><span>为什么需要确认</span><span>状态与分数</span><span>负责人 / 截止时间</span><span>操作</span></div>
          {visible.map((task) => (
            <article key={task.id} className={task.route === 'SAFE_DEGRADE' ? 'safe-degrade-row' : ''}>
              <div className="task-identity"><img src={task.thumbnailUrl} alt="" /><span><strong>{task.batchNo}</strong><small>{task.id}</small><code>{task.inspectionId}</code></span></div>
              <div className="route-cell">
                {task.route === 'SAFE_DEGRADE' ? <ShieldAlert size={17} /> : task.held ? <AlertTriangle size={17} /> : <span className="route-dot" />}
                <span><strong>{routeLabels[task.route]}</strong><small>{task.held ? '批次流转已暂停' : '未执行外部质量写操作'}</small></span>
              </div>
              <div className="risk-cell"><StatusBadge status={task.held ? 'BATCH_HELD' : 'REVIEW_REQUIRED'} size="sm" /><strong>{formatScore(task.score)}</strong><small>{task.score === undefined ? '模型未返回' : '异常分数'}</small></div>
              <div className="owner-cell"><span><UserRound size={15} />{task.assignee ?? '未认领'}</span><span className={task.route === 'SAFE_DEGRADE' ? 'overdue' : ''}><Clock3 size={15} />{formatDateTime(task.slaAt)}</span></div>
              <button className="row-action" onClick={() => navigate(`/reviews/${task.id}`)}>{task.assignee ? '打开复核' : '认领并复核'}<ArrowRight size={16} /></button>
            </article>
          ))}
          {visible.length === 0 && <div className="empty-row">当前筛选条件下没有复核任务。</div>}
        </div>
      )}

      <div className="queue-footnote"><ShieldAlert size={17} /><span><strong>安全降级任务优先：</strong>模型不可用时系统不会自动放行。请基于原图和现场标准判断，必要时选择“无法判断”并升级。</span></div>
    </div>
  )
}
