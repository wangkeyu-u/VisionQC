import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation } from 'wouter'
import { AlertTriangle, ArrowRight, Clock3, Filter, Search, ShieldAlert, UserRound } from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import type { ReviewTask } from '../types'
import { formatDateTime, formatScore } from '../utils'

const routeLabels = {
  GREY_ZONE: '双阈值灰区',
  HIGH_SCORE_HOLD: '高分暂扣',
  SAFE_DEGRADE: '安全降级',
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
        <div><span className="page-kicker">人工复核 · 风险队列</span><h1>人工复核队列</h1><p>按质量风险与 SLA 排序。模型结果用于提供证据，不替代你的现场质量判断。</p></div>
        <div className="queue-metrics"><div><span>待处理</span><strong>{tasks?.length ?? '—'}</strong></div><div><span>已暂扣</span><strong>{tasks ? tasks.filter((task) => task.held).length : '—'}</strong></div><div><span>SLA 风险</span><strong>{tasks ? tasks.filter((task) => task.priority === 'CRITICAL').length : '—'}</strong></div></div>
      </div>

      <div className="queue-toolbar panel">
        <label className="search-field"><Search size={16} /><input aria-label="搜索复核任务" placeholder="搜索任务、检测或批次…" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <div className="queue-filters" aria-label="复核任务筛选">
          <Filter size={15} />
          {([['ALL', '全部'], ['HELD', '已暂扣'], ['UNASSIGNED', '待认领']] as const).map(([value, label]) => (
            <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
        <span className="queue-sort">排序：风险优先 · SLA 升序</span>
      </div>

      {error ? <ErrorState error={error} onRetry={load} /> : !tasks ? <LoadingState label="正在读取复核任务…" /> : (
        <div className="review-table panel">
          <div className="review-table-head"><span>证据 / 任务</span><span>触发路径</span><span>风险与分数</span><span>责任 / SLA</span><span>操作</span></div>
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
