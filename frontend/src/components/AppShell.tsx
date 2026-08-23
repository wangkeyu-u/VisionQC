import {
  Activity,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  Cpu,
  Database,
  Factory,
  FileWarning,
  FlaskConical,
  HardDrive,
  ImagePlus,
  ScanLine,
  Server,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  Wifi,
  X,
} from 'lucide-react'
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import type { GatewayStatus, SystemHealth, TenantContext } from '../types'

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
  { to: '/', label: '工作首页', icon: Activity, end: true },
  { to: '/reviews', label: '待我复核', icon: ClipboardCheck },
  { to: '/incidents', label: '质量事件', icon: FileWarning },
  { to: '/operations', label: '设备连接', icon: Server },
  { to: '/modelops', label: '模型证据', icon: FlaskConical },
]

function connectionSummary(health: SystemHealth | null, gateways: GatewayStatus[] | null, error: string | null) {
  if (error) return { label: '连接需要检查', tone: 'danger' }
  if (!health || !gateways) return { label: '正在检查连接', tone: 'info' }
  if (health.status !== 'ok') return { label: '核心服务异常', tone: 'danger' }
  if (gateways.length === 0 || gateways.some((row) => row.status !== 'ONLINE')) return { label: '网页可用，设备待检查', tone: 'warning' }
  return { label: '系统连接正常', tone: 'success' }
}

function HelpDrawer({ onClose }: { onClose: () => void }) {
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="support-drawer" role="dialog" aria-modal="true" aria-labelledby="help-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-heading">
          <div><span className="drawer-icon"><BookOpen size={20} /></span><span><strong id="help-title">第一次使用 VisionQC</strong><small>不需要了解模型或编程，照着下面三步操作即可。</small></span></div>
          <button className="icon-button" aria-label="关闭使用帮助" onClick={onClose}><X size={18} /></button>
        </div>

        <ol className="quick-start-list">
          <li><span>1</span><div><strong>准备一张图片</strong><p>没有工厂图片也没关系，点击“使用演示图片”即可载入 Blender 生成的可追溯示例。</p></div></li>
          <li><span>2</span><div><strong>查看系统指出的可疑区域</strong><p>分数和热力图只是提醒，不会直接把产品判成不合格。</p></div></li>
          <li><span>3</span><div><strong>由人做最终决定</strong><p>在“待我复核”中选择合格、返工、报废或继续调查，并留下原因。</p></div></li>
        </ol>

        <Link className="primary-button full-button" href="/upload?demo=1" onClick={onClose}><ImagePlus size={17} />使用演示图片开始</Link>

        <section className="plain-language-guide">
          <h2>页面怎么分工</h2>
          <dl>
            <div><dt>工作首页</dt><dd>先看哪里需要你处理，以及系统连接是否正常。</dd></div>
            <div><dt>待我复核</dt><dd>查看图片和可疑区域，并记录人工结论。</dd></div>
            <div><dt>质量事件</dt><dd>跟踪暂扣、工单、验证和关闭结果。</dd></div>
            <div><dt>设备连接</dt><dd>确认现场电脑是否在线，图片有没有积压。</dd></div>
            <div><dt>模型证据</dt><dd>给技术或审核人员查看模型版本和能否上线；日常操作可以不看。</dd></div>
          </dl>
        </section>

        <details className="glossary">
          <summary>看不懂英文缩写？展开术语解释</summary>
          <p><strong>Gateway（现场接入程序）</strong>：把相机或文件夹里的图片安全送进系统。</p>
          <p><strong>Deployment Pack（客户配置包）</strong>：保存当前工厂的产品、工位、阈值和系统连接配置。</p>
          <p><strong>MES / QMS</strong>：分别是生产管理系统和质量管理系统。本演示使用模拟接口。</p>
          <p><strong>ModelOps（模型管理）</strong>：记录模型版本、评测证据和上线门槛。</p>
        </details>
      </aside>
    </div>
  )
}

function ConnectionDrawer({
  context,
  gateways,
  health,
  error,
  loading,
  onRefresh,
  onClose,
}: {
  context: TenantContext | null
  gateways: GatewayStatus[] | null
  health: SystemHealth | null
  error: string | null
  loading: boolean
  onRefresh: () => Promise<void>
  onClose: () => void
}) {
  const onlineGateways = gateways?.filter((item) => item.status === 'ONLINE').length ?? 0
  const checks = [
    { label: '业务服务', ok: Boolean(context) && !error, detail: error ?? '客户与任务数据可以正常读取。', icon: Wifi },
    { label: '图片存储', ok: health?.checks.storage === true, detail: health ? '原图和热力图存储服务已响应。' : '正在等待服务状态。', icon: Database },
    { label: '异常检测服务', ok: health?.checks.model === true, detail: health ? '模型服务可以接收检测任务。' : '正在等待服务状态。', icon: Cpu },
    { label: '现场采集设备', ok: Boolean(gateways?.length) && onlineGateways === gateways?.length, detail: gateways ? `${onlineGateways}/${gateways.length} 个现场接入程序在线。手动上传不依赖此项。` : '正在读取现场设备。', icon: HardDrive },
  ]
  const manualReady = checks.slice(0, 3).every((item) => item.ok)

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="support-drawer connection-drawer" role="dialog" aria-modal="true" aria-labelledby="connection-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-heading">
          <div><span className={`drawer-icon ${manualReady ? 'ready' : 'attention'}`}><Wifi size={20} /></span><span><strong id="connection-title">系统连接检查</strong><small>{manualReady ? '可以开始上传图片并完成演示流程。' : '请先处理下方未通过的项目。'}</small></span></div>
          <button className="icon-button" aria-label="关闭连接检查" onClick={onClose}><X size={18} /></button>
        </div>

        <div className={`readiness-verdict ${manualReady ? 'ready' : 'blocked'}`}>
          {manualReady ? <CheckCircle2 size={22} /> : <ShieldAlert size={22} />}
          <span><strong>{manualReady ? '手动演示已就绪' : '暂时不能安全开始'}</strong><small>{manualReady ? '即使现场设备离线，也可以使用网页中的演示图片。' : '点击重新检查；若仍失败，请确认 Docker 服务已经启动。'}</small></span>
        </div>

        <ul className="connection-checks">
          {checks.map(({ label, ok, detail, icon: Icon }) => <li key={label} className={ok ? 'passed' : 'failed'}><Icon size={18} /><span><strong>{label}</strong><small>{detail}</small></span><b>{ok ? '正常' : loading ? '检查中' : '需检查'}</b></li>)}
        </ul>

        <div className="drawer-actions">
          <button className="secondary-button" disabled={loading} onClick={() => void onRefresh()}>{loading ? '正在检查…' : '重新检查连接'}</button>
          <Link className="primary-button" href="/operations" onClick={onClose}>查看设备详情</Link>
        </div>
        <p className="mode-explanation"><ShieldCheck size={15} />当前是演示环境：MES、QMS 和部分图片为模拟数据，不会操作真实生产系统。</p>
      </aside>
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const [location, navigate] = useLocation()
  const [context, setContext] = useState<TenantContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [connectionOpen, setConnectionOpen] = useState(false)

  async function refreshRuntime() {
    const [nextGateways, nextHealth] = await Promise.all([
      visionQcApi.listGatewayStatuses(),
      visionQcApi.getSystemHealth(),
    ])
    setGateways(nextGateways)
    setSystemHealth(nextHealth)
  }

  async function refresh() {
    setLoading(true)
    try {
      const [nextContext, nextGateways, nextHealth] = await Promise.all([
        visionQcApi.getTenantContext(),
        visionQcApi.listGatewayStatuses(),
        visionQcApi.getSystemHealth(),
      ])
      setContext(nextContext)
      setGateways(nextGateways)
      setSystemHealth(nextHealth)
      setError(null)
    } catch {
      setError('系统暂时无法读取完整连接状态。你可以重新检查；若仍失败，请确认演示服务已经启动。')
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
      await refreshRuntime()
      setError(null)
      navigate('/')
    } catch {
      setError('无法切换到这个客户环境。请确认当前演示账号拥有切换权限，然后重试。')
    } finally {
      setLoading(false)
    }
  }

  const health = connectionSummary(systemHealth, gateways, error)
  const activeDeployment = context?.currentDeployment

  return (
    <DeploymentContextState.Provider value={{ context, loading, error, refresh }}>
      <div className="app-shell">
        <header className="global-header">
          <Link href="/" className="brand-lockup" aria-label="VisionQC 工作首页">
            <span className="brand-mark" aria-hidden="true"><ScanLine size={20} /></span>
            <span className="brand-name">Vision<span>QC</span></span>
            <span className="brand-divider" aria-hidden="true" />
            <span className="brand-context">质量工作台</span>
          </Link>

          <nav className="primary-nav" aria-label="主导航">
            {navItems.map(({ to, label, icon: Icon, end }) => {
              const isActive = end ? location === to : location.startsWith(to)
              return <Link key={to} href={to} className={isActive ? 'active' : undefined} aria-current={isActive ? 'page' : undefined}><Icon size={16} aria-hidden="true" /><span>{label}</span></Link>
            })}
          </nav>

          <div className="header-actions">
            <span className="demo-mode-badge">演示环境</span>
            <button className="help-button" onClick={() => setHelpOpen(true)}><BookOpen size={16} />使用帮助</button>
            <Link className="upload-link" href="/upload"><UploadCloud size={15} />上传图片</Link>
            <div className="operator-chip" aria-label="当前操作人员：演示质量经理"><span className="operator-avatar" aria-hidden="true">林</span><span><strong>演示质量经理</strong><small>已登录</small></span></div>
          </div>
        </header>

        <div className="context-bar">
          <div className="context-select-group">
            <Factory size={17} aria-hidden="true" />
            <label><span>当前工厂</span><select aria-label="切换客户部署" value={context?.tenant.id ?? ''} disabled={loading || !context || context.availableTenants.length < 2} onChange={(event) => void switchTenant(event.target.value)}>{context?.availableTenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>) ?? <option value="">读取中…</option>}</select></label>
          </div>
          <div className="context-pack"><span>当前产品配置</span><strong>{activeDeployment?.displayName ?? '等待配置'}</strong><details><summary>查看配置编号</summary><code>{activeDeployment?.packKey ?? '—'} · v{activeDeployment?.version ?? '—'}</code></details></div>
          <div className="context-facts"><button className={`health-indicator ${health.tone}`} onClick={() => setConnectionOpen(true)} aria-haspopup="dialog"><i />{health.label}<span>查看</span></button></div>
        </div>

        {error && <div className="global-error" role="status"><ShieldAlert size={16} />{error}<button className="text-button" onClick={() => void refresh()}>重新检查</button></div>}

        <div className="boundary-strip"><ShieldCheck size={16} aria-hidden="true" /><span><strong>请注意</strong> 系统只指出“哪里看起来可疑”，不会代替人确认合格、不合格或故障原因。</span></div>
        <main className="workspace">{children}</main>

        {helpOpen && <HelpDrawer onClose={() => setHelpOpen(false)} />}
        {connectionOpen && <ConnectionDrawer context={context} gateways={gateways} health={systemHealth} error={error} loading={loading} onRefresh={refresh} onClose={() => setConnectionOpen(false)} />}
      </div>
    </DeploymentContextState.Provider>
  )
}
