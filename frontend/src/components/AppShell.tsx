import { Activity, Bell, ChevronDown, ClipboardCheck, FileWarning, Factory, FlaskConical, ScanLine, Server, ShieldCheck, UploadCloud } from 'lucide-react'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import type { GatewayStatus, TenantContext } from '../types'

interface DeploymentContextValue {
  context: TenantContext | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

const DeploymentContextState = createContext<DeploymentContextValue | undefined>(undefined)

export function useDeploymentContext(): DeploymentContextValue {
  const value = useContext(DeploymentContextState)
  if (!value) throw new Error('useDeploymentContext must be used inside AppShell')
  return value
}

const navItems = [
  { to: '/', label: '运营总览', icon: Activity, end: true },
  { to: '/reviews', label: '复核工作台', icon: ClipboardCheck },
  { to: '/incidents', label: '质量事件', icon: FileWarning },
  { to: '/operations', label: 'Gateway 运营', icon: Server },
  { to: '/modelops', label: 'ModelOps', icon: FlaskConical },
]

function gatewaySummary(rows: GatewayStatus[] | null) {
  if (!rows) return { label: 'Gateway 状态读取中', tone: 'info' }
  if (rows.length === 0) return { label: 'Gateway 未接入', tone: 'warning' }
  const online = rows.filter((row) => row.status === 'ONLINE').length
  if (online === rows.length) return { label: `Gateway ${online}/${rows.length} 在线`, tone: 'success' }
  return { label: `Gateway ${online}/${rows.length} 在线`, tone: 'warning' }
}

export function AppShell({ children }: { children: ReactNode }) {
  const [location, navigate] = useLocation()
  const [context, setContext] = useState<TenantContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)

  async function refreshGatewayHealth() {
    try { setGateways(await visionQcApi.listGatewayStatuses()) } catch { setGateways(null) }
  }

  async function refresh() {
    setLoading(true)
    try {
      const next = await visionQcApi.getTenantContext()
      setContext(next)
      setError(null)
      await refreshGatewayHealth()
    } catch {
      setError('部署上下文暂时不可用；当前页面以安全降级模式显示。')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void refresh() }, [])

  async function switchTenant(tenantId: string) {
    if (!context || tenantId === context.tenant.id) return
    setLoading(true)
    try {
      const next = await visionQcApi.switchTenant(tenantId)
      setContext(next)
      setError(null)
      await refreshGatewayHealth()
      navigate('/')
    } catch {
      setError('客户切换被拒绝；请确认当前账号拥有 FDE / 管理员租户切换权限。')
    } finally {
      setLoading(false)
    }
  }

  const health = gatewaySummary(gateways)
  const activeDeployment = context?.currentDeployment

  return (
    <DeploymentContextState.Provider value={{ context, loading, error, refresh }}>
      <div className="app-shell">
        <header className="global-header">
          <Link href="/" className="brand-lockup" aria-label="VisionQC 运营总览">
            <span className="brand-mark" aria-hidden="true"><ScanLine size={20} /></span>
            <span className="brand-name">Vision<span>QC</span></span>
            <span className="brand-divider" aria-hidden="true" />
            <span className="brand-context">质量控制中心</span>
          </Link>

          <nav className="primary-nav" aria-label="主导航">
            {navItems.map(({ to, label, icon: Icon, end }) => {
              const isActive = end ? location === to : location.startsWith(to)
              return <Link key={to} href={to} className={isActive ? 'active' : undefined} aria-current={isActive ? 'page' : undefined}><Icon size={16} aria-hidden="true" /><span>{label}</span></Link>
            })}
          </nav>

          <div className="header-actions">
            <Link className="upload-link" href="/upload"><UploadCloud size={15} />手动上传</Link>
            <button className="icon-button" aria-label="通知"><Bell size={17} /><i /></button>
            <div className="operator-chip"><span className="operator-avatar" aria-hidden="true">林</span><span><strong>演示质量经理</strong><small>Quality Manager</small></span><ChevronDown size={14} aria-hidden="true" /></div>
          </div>
        </header>

        <div className="context-bar">
          <div className="context-select-group">
            <Factory size={16} aria-hidden="true" />
            <label><span>当前客户</span><select aria-label="切换客户部署" value={context?.tenant.id ?? ''} disabled={loading || !context || context.availableTenants.length < 2} onChange={(event) => void switchTenant(event.target.value)}>{context?.availableTenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>) ?? <option value="">读取中…</option>}</select></label>
            <ChevronDown size={14} aria-hidden="true" />
          </div>
          <div className="context-pack"><span>当前 Deployment Pack</span><strong>{activeDeployment?.displayName ?? '等待部署上下文'}</strong><code>{activeDeployment?.packKey ?? '—'} · v{activeDeployment?.version ?? '—'}</code></div>
          <div className="context-facts"><span className={`health-indicator ${health.tone}`}><i />{health.label}</span><span className="context-divider" /><span className="system-health"><ShieldCheck size={14} />系统审计链正常</span></div>
        </div>

        {error && <div className="global-error" role="status"><ShieldCheck size={15} />{error}<button className="text-button" onClick={() => void refresh()}>重新读取</button></div>}

        <div className="boundary-strip"><ShieldCheck size={15} aria-hidden="true" /><span><strong>判定边界</strong> 模型标记的是异常区域；异常不等于已确认缺陷，最终质量结论由授权人员负责。</span></div>
        <main className="workspace">{children}</main>
      </div>
    </DeploymentContextState.Provider>
  )
}
