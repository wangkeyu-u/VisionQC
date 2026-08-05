import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, FileWarning, RefreshCw } from 'lucide-react'
import { Link } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import type { IncidentSummary } from '../types'
import { formatDateTime } from '../utils'

const statusLabels: Record<string, string> = {
  OPEN: '已创建',
  ACTION_PENDING: '待执行',
  ACTION_EXECUTING: '执行中',
  ACTION_COMPLETED: '待验证',
  ACTION_FAILED: '需人工处理',
  VERIFYING: '等待验证',
  CLOSED: '已关闭',
  ESCALATED: '已升级',
}
const dispositionLabels: Record<string, string> = { REWORK: '返工', SCRAP: '报废', INVESTIGATE: '调查' }

export function IncidentsPage() {
  const [incidents, setIncidents] = useState<IncidentSummary[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const load = useCallback(async () => {
    try { setError(null); setIncidents(await visionQcApi.listIncidents()) } catch (caught) { setError(caught) }
  }, [])
  useEffect(() => { void load() }, [load])

  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!incidents) return <div className="page"><LoadingState label="正在读取质量事件…" /></div>

  return (
    <div className="page incidents-page">
      <div className="page-heading"><div><span className="page-kicker">质量事件 · 处置闭环</span><h1>质量事件</h1><p>按处置状态追踪人工确认后的事件；外部 MES / QMS 动作和关闭证据在详情页留存。</p></div><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />刷新</button></div>
      <div className="incident-list-panel work-panel">
        <div className="panel-heading compact-heading"><div><span className="section-index">01</span><h2>当前客户事件</h2></div><span className="panel-note">API 返回 {incidents.length} 条</span></div>
        {incidents.length === 0 ? <div className="inline-empty"><FileWarning size={19} /><strong>暂无质量事件</strong><span>人工复核确认不合格或调查后，事件会出现在这里。</span></div> : <div className="incident-list-table"><div className="incident-list-head"><span>事件 / 批次</span><span>状态</span><span>处置</span><span>负责人</span><span>更新时间</span><span /></div>{incidents.map((incident) => <Link className="incident-list-row" key={incident.id} href={`/incidents/${incident.id}`}><span><strong>{incident.id}</strong><small>{incident.productCode} · {incident.batchNo} · {incident.station}</small></span><StatusBadge status={incident.status === 'ACTION_COMPLETED' ? 'VERIFYING' : incident.status as never} label={statusLabels[incident.status] ?? incident.status} size="sm" /><span>{dispositionLabels[incident.disposition] ?? incident.disposition}</span><span>{incident.owner ?? '待分配'}</span><span>{formatDateTime(incident.updatedAt, true)}</span><ArrowRight size={15} /></Link>)}</div>}
      </div>
      <div className="demo-disclosure"><span className="disclosure-label">闭环边界</span><span>只有具名人工决定才会创建质量事件；异常分数、热力图和自动策略不会直接写入不合格结论。</span><Link href="/reviews">去复核队列<ArrowRight size={14} /></Link></div>
    </div>
  )
}
