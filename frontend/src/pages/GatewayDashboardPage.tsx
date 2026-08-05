import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, CheckCircle2, Database, RefreshCw, Server, UploadCloud, WifiOff } from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useDeploymentContext } from '../components/AppShell'
import type { GatewayStatus } from '../types'
import { formatDateTime } from '../utils'

export function GatewayDashboardPage() {
  const { context } = useDeploymentContext()
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)
  const [error, setError] = useState<unknown>(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      setGateways(await visionQcApi.listGatewayStatuses())
    } catch (caught) {
      setError(caught)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = window.setInterval(() => void load(), 15_000)
    return () => window.clearInterval(timer)
  }, [load])

  const summary = useMemo(() => {
    const rows = gateways ?? []
    return {
      gateways: rows.length,
      online: rows.filter((row) => row.status === 'ONLINE').length,
      backlog: rows.reduce((total, row) => total + row.queueDepth, 0),
      failures: rows.reduce((total, row) => total + row.uploadFailureCount, 0),
    }
  }, [gateways])

  return (
    <div className="page gateway-page">
      <div className="page-heading">
        <div>
          <span className="page-kicker">Edge Gateway · 工位状态</span>
          <h1>工位 / Gateway 运营监测</h1>
          <p>查看现场网关心跳、目录采集积压与上传可靠性。队列项会保留在本地，网关异常不会默认放行图片。</p>
        </div>
        <button className="secondary-button" onClick={() => void load()}><RefreshCw size={14} />刷新状态</button>
      </div>

      <div className="gateway-summary">
        <article className="panel"><span>已注册 Gateway</span><strong>{summary.gateways.toString().padStart(2, '0')}</strong><small>{context?.tenant.name ?? '当前租户'} · JWT scope</small></article>
        <article className="panel"><span>在线工位</span><strong>{summary.online.toString().padStart(2, '0')}</strong><small>心跳在 {15} 秒内更新</small></article>
        <article className={summary.backlog ? 'panel gateway-warning' : 'panel'}><span>本地待补传</span><strong>{summary.backlog.toString().padStart(2, '0')}</strong><small>待上传 / 重试 / 失败</small></article>
        <article className={summary.failures ? 'panel gateway-danger' : 'panel'}><span>累计上传失败</span><strong>{summary.failures.toString().padStart(2, '0')}</strong><small>错误保留在网关审计队列</small></article>
      </div>

      {error ? <ErrorState error={error} onRetry={load} /> : !gateways ? <LoadingState label="正在读取工位网关状态…" /> : gateways.length === 0 ? (
        <div className="state-panel"><Server size={25} /><div><strong>当前租户还没有心跳记录</strong><span>启动对应 Deployment Pack 的 edge-gateway 后，状态会自动出现在这里。</span></div></div>
      ) : (
        <div className="gateway-table panel">
          <div className="gateway-table-head"><span>工位 / Gateway</span><span>运行状态</span><span>本地队列</span><span>上传统计</span><span>最近心跳</span></div>
          {gateways.map((gateway) => (
            <article key={gateway.gatewayId}>
              <div className="gateway-identity"><div className="gateway-icon"><Server size={18} /></div><span><strong>{gateway.stationCode}</strong><small>{gateway.gatewayId} · v{gateway.gatewayVersion}</small><code>{gateway.deploymentPackKey ?? 'pack unavailable'}</code></span></div>
              <div className="gateway-status"><StatusBadge status={gateway.status} /><small>{gateway.lastError ?? (gateway.status === 'ONLINE' ? '心跳与后端连通正常' : '请检查边缘节点与网络')}</small></div>
              <div className="gateway-queue"><strong>{gateway.queueDepth}</strong><span>待补传</span>{gateway.queueDepth > 0 ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div>
              <div className="gateway-counters"><span><UploadCloud size={13} />成功 {gateway.uploadSuccessCount}</span><span className={gateway.uploadFailureCount ? 'danger-text' : ''}><WifiOff size={13} />失败 {gateway.uploadFailureCount}</span></div>
              <div className="gateway-heartbeat"><strong>{formatDateTime(gateway.lastHeartbeatAt, true)}</strong><small>{gateway.lastUploadSucceededAt ? `最近上传 ${formatDateTime(gateway.lastUploadSucceededAt)}` : '尚无成功上传时间'}</small></div>
            </article>
          ))}
        </div>
      )}

      <div className="gateway-notes">
        <div><Database size={17} /><span><strong>本地持久化队列</strong>图片上传失败时不会从 spool 删除；恢复网络后按指数退避继续补传。</span></div>
        <div><Activity size={17} /><span><strong>质量门禁与模型边界</strong>过暗、过曝、模糊或损坏文件在网关审计中标为输入拒绝；模型异常仍显示为异常证据，不改写为语义缺陷。</span></div>
      </div>
    </div>
  )
}
