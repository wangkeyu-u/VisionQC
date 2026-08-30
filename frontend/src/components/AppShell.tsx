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
  LifeBuoy,
  ScanLine,
  Server,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  Wifi,
  X,
} from 'lucide-react'
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { useI18n } from '../hooks/useI18n'
import { applyRuntimeIndustryPack, useTenantConfig, localized, type Language } from '../config/tenant'
import type { GatewayStatus, SystemHealth, TenantContext } from '../types'
import type { MessageKey } from '../i18n'

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

const navItems: Array<{ to: string; key: MessageKey; icon: typeof Activity; end?: boolean }> = [
  { to: '/', key: 'nav.overview', icon: Activity, end: true },
  { to: '/start', key: 'nav.start', icon: ScanLine },
  { to: '/upload', key: 'nav.upload', icon: UploadCloud },
  { to: '/reviews', key: 'nav.reviews', icon: ClipboardCheck },
  { to: '/incidents', key: 'nav.incidents', icon: FileWarning },
  { to: '/operations', key: 'nav.gateway', icon: Server },
  { to: '/modelops', key: 'nav.modelops', icon: FlaskConical },
]

function connectionSummary(health: SystemHealth | null, gateways: GatewayStatus[] | null, error: string | null, t: ReturnType<typeof useI18n>['t']) {
  if (error) return { label: t('header.connectionIssue'), tone: 'danger' }
  if (!health || !gateways) return { label: t('header.loading'), tone: 'info' }
  if (health.status !== 'ok') return { label: t('header.connectionIssue'), tone: 'danger' }
  if (gateways.length === 0 || gateways.some((row) => row.status !== 'ONLINE')) return { label: t('header.connection'), tone: 'warning' }
  return { label: t('header.connection'), tone: 'success' }
}

function HelpDrawer({ onClose }: { onClose: () => void }) {
  const { t, language } = useI18n()
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="support-drawer" role="dialog" aria-modal="true" aria-labelledby="help-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-heading">
          <div className="drawer-heading-copy"><span className="drawer-icon"><LifeBuoy size={20} /></span><span><strong id="help-title">{t('help.title')}</strong><small>{t('help.subtitle')}</small></span></div>
          <button className="icon-button" aria-label={t('common.cancel')} onClick={onClose}><X size={18} /></button>
        </div>

        <ol className="quick-start-list">
          <li><span>01</span><div><strong>{t('help.step1')}</strong><p>{t('help.step1Body')}</p></div></li>
          <li><span>02</span><div><strong>{t('help.step2')}</strong><p>{t('help.step2Body')}</p></div></li>
          <li><span>03</span><div><strong>{t('help.step3')}</strong><p>{t('help.step3Body')}</p></div></li>
        </ol>

        <Link className="primary-button full-button" href="/upload?demo=1" onClick={onClose}><UploadCloud size={17} />{t('help.start')}</Link>

        <section className="plain-language-guide">
          <h2>{t('help.pages')}</h2>
          <dl>
            <div><dt>{t('nav.overview')}</dt><dd>{t('overview.subtitle')}</dd></div>
            <div><dt>{t('nav.reviews')}</dt><dd>{t('help.step3Body')}</dd></div>
            <div><dt>{t('nav.incidents')}</dt><dd>{t('incidents.subtitle')}</dd></div>
            <div><dt>{t('nav.gateway')}</dt><dd>{t('help.gatewayBody')}</dd></div>
            <div><dt>{t('nav.modelops')}</dt><dd>{t('modelops.subtitle')}</dd></div>
          </dl>
        </section>

        <details className="glossary">
          <summary>{t('help.connectors')}</summary>
          <p><strong>{t('help.gateway')}</strong>{language === 'zh' ? '：' : ': '}{t('help.gatewayBody')}</p>
          <p><strong>{t('help.connectors')}</strong>{language === 'zh' ? '：' : ': '}{t('help.connectorsBody')}</p>
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
  const { t } = useI18n()
  const onlineGateways = gateways?.filter((item) => item.status === 'ONLINE').length ?? 0
  const checks = [
    { label: t('connection.business'), ok: Boolean(context) && !error, detail: error ?? t('header.connection'), icon: Wifi },
    { label: t('connection.storage'), ok: health?.checks.storage === true, detail: health ? t('header.connection') : t('common.loading'), icon: Database },
    { label: t('connection.model'), ok: health?.checks.model === true, detail: health ? t('header.connection') : t('common.loading'), icon: Cpu },
    { label: t('connection.device'), ok: Boolean(gateways?.length) && onlineGateways === gateways?.length, detail: gateways ? `${onlineGateways}/${gateways.length} · ${t('connection.device')}` : t('common.loading'), icon: HardDrive },
  ]
  const manualReady = checks.slice(0, 3).every((item) => item.ok)
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="support-drawer connection-drawer" role="dialog" aria-modal="true" aria-labelledby="connection-title" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-heading">
          <div className="drawer-heading-copy"><span className={`drawer-icon ${manualReady ? 'ready' : 'attention'}`}><Wifi size={20} /></span><span><strong id="connection-title">{t('connection.title')}</strong><small>{manualReady ? t('connection.drawerReady') : t('connection.drawerBlocked')}</small></span></div>
          <button className="icon-button" aria-label={t('common.cancel')} onClick={onClose}><X size={18} /></button>
        </div>
        <div className={`readiness-verdict ${manualReady ? 'ready' : 'blocked'}`}>
          {manualReady ? <CheckCircle2 size={22} /> : <ShieldAlert size={22} />}
          <span><strong>{manualReady ? t('connection.ready') : t('connection.blocked')}</strong><small>{manualReady ? t('connection.readyBody') : t('connection.blockedBody')}</small></span>
        </div>
        <ul className="connection-checks">
          {checks.map(({ label, ok, detail, icon: Icon }) => <li key={label} className={ok ? 'passed' : 'failed'}><Icon size={18} /><span><strong>{label}</strong><small>{detail}</small></span><b>{ok ? t('connection.ok') : loading ? t('connection.checking') : t('connection.needsCheck')}</b></li>)}
        </ul>
        <div className="drawer-actions">
          <button className="secondary-button" disabled={loading} onClick={() => void onRefresh()}>{loading ? t('connection.checking') : t('connection.recheck')}</button>
          <Link className="primary-button" href="/operations" onClick={onClose}>{t('connection.deviceDetails')}</Link>
        </div>
        <p className="mode-explanation"><ShieldCheck size={15} />{t('header.simulation')} · {t('header.synthetic')} · {t('header.noGo')}</p>
      </aside>
    </div>
  )
}

function LanguageToggle() {
  const { config, setLanguage } = useTenantConfig()
  const { t } = useI18n()
  const next: Language = config.language === 'zh' ? 'en' : 'zh'
  return <button className="language-toggle" aria-label={t('header.language')} onClick={() => setLanguage(next)}><span>{config.language === 'zh' ? '中' : 'EN'}</span>{t('header.language')}</button>
}

export function AppShell({ children }: { children: ReactNode }) {
  const [location, navigate] = useLocation()
  const { config, industryPack, themeStyle } = useTenantConfig()
  const { t, language } = useI18n()
  const [context, setContext] = useState<TenantContext | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [gateways, setGateways] = useState<GatewayStatus[] | null>(null)
  const [systemHealth, setSystemHealth] = useState<SystemHealth | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const [connectionOpen, setConnectionOpen] = useState(false)

  useEffect(() => {
    document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN'
    document.title = `${config.branding.displayName} · ${config.branding.siteName}`
  }, [config.branding.displayName, config.branding.siteName, language])

  async function refreshRuntime() {
    const [nextGateways, nextHealth] = await Promise.all([visionQcApi.listGatewayStatuses(), visionQcApi.getSystemHealth()])
    setGateways(nextGateways)
    setSystemHealth(nextHealth)
  }

  async function refresh() {
    setLoading(true)
    try {
      const [nextContext, nextGateways, nextHealth] = await Promise.all([visionQcApi.getTenantContext(), visionQcApi.listGatewayStatuses(), visionQcApi.getSystemHealth()])
      setContext(nextContext)
      setGateways(nextGateways)
      setSystemHealth(nextHealth)
      setError(null)
    } catch {
      setError(t('error.load'))
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
      setError(language === 'zh' ? '无法切换到这个企业环境。请确认当前演示账号拥有权限，然后重试。' : 'This tenant could not be selected. Check access and try again.')
    } finally {
      setLoading(false)
    }
  }

  const health = connectionSummary(systemHealth, gateways, error, t)
  const runtimeContext = useMemo(() => {
    if (!context) return context
    return { ...context, currentDeployment: applyRuntimeIndustryPack(context.currentDeployment, industryPack, config.setupComplete) }
  }, [config.setupComplete, context, industryPack])
  const activeDeployment = runtimeContext?.currentDeployment
  const currentTenantLabel = context?.tenant.name ?? (language === 'zh' ? '正在读取企业…' : 'Reading tenant…')

  return (
    <DeploymentContextState.Provider value={{ context: runtimeContext, loading, error, refresh }}>
      <div className={`app-shell density-${config.branding.density}`} style={themeStyle}>
        <header className="global-header">
          <Link href="/" className="brand-lockup" aria-label={`${config.branding.displayName} ${t('brand.workspace')}`}>
            {config.branding.logoUrl ? <img className="tenant-logo" src={config.branding.logoUrl} alt={`${config.branding.displayName} logo`} /> : <span className="brand-mark" aria-hidden="true"><ScanLine size={20} /></span>}
            <span className="brand-name">{config.branding.displayName}</span>
            <span className="brand-divider" aria-hidden="true" />
            <span className="brand-context">{config.branding.siteName}</span>
          </Link>

          <nav className="primary-nav" aria-label={language === 'zh' ? '主导航' : 'Primary navigation'}>
            {navItems.map(({ to, key, icon: Icon, end }) => {
              const isActive = end ? location === to : location === to || location.startsWith(`${to}/`)
              return <Link key={to} href={to} className={isActive ? 'active' : undefined} aria-current={isActive ? 'page' : undefined}><Icon size={16} aria-hidden="true" /><span>{t(key)}</span></Link>
            })}
          </nav>

          <div className="header-actions">
            <span className="demo-mode-badge"><span className="live-dot" />{t('header.demo')}</span>
            <span className="truth-chip">{t('header.simulation')}</span>
            <LanguageToggle />
            <button className="help-button" onClick={() => setHelpOpen(true)}><BookOpen size={16} />{t('header.help')}</button>
            <Link className="upload-link" href="/upload"><UploadCloud size={15} />{t('overview.upload')}</Link>
            <Link className="settings-link" href="/settings" aria-label={t('nav.setup')}><span>{config.branding.displayName.slice(0, 1).toUpperCase()}</span></Link>
          </div>
        </header>

        <div className="context-bar">
          <div className="context-identity"><Factory size={17} aria-hidden="true" /><span><small>{t('header.tenant')}</small><strong>{config.branding.displayName}</strong><em>{currentTenantLabel}</em></span></div>
          <label className="context-select"><span>{language === 'zh' ? '切换企业部署' : 'Switch tenant deployment'}</span><select aria-label={language === 'zh' ? '切换客户部署' : 'Switch tenant deployment'} value={context?.tenant.id ?? ''} disabled={loading || !context || context.availableTenants.length < 2} onChange={(event) => void switchTenant(event.target.value)}>{context?.availableTenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>) ?? <option value="">{t('common.loading')}</option>}</select></label>
          <div className="context-pack"><span>{t('header.industry')}</span><strong>{localized(industryPack.name, language)}</strong><small>{localized(industryPack.terms.item, language, true)} · {activeDeployment?.packKey ?? 'tenant-config.v1'}</small></div>
          <div className="context-facts"><button className={`health-indicator ${health.tone}`} onClick={() => setConnectionOpen(true)} aria-haspopup="dialog"><i />{health.label}<span>{t('header.connectionCheck')}</span></button></div>
        </div>

        {error && <div className="global-error" role="status"><ShieldAlert size={16} />{error}<button className="text-button" onClick={() => void refresh()}>{t('common.retry')}</button></div>}

        <div className="boundary-strip"><ShieldCheck size={16} aria-hidden="true" /><span><strong>{t('header.noGo')}</strong><span>{t('header.platformBoundary')}</span><div className="boundary-tags"><i>{t('header.simulation')}</i><i>{t('header.synthetic')}</i>{industryPack.id === 'automotive-paint' && <i>{t('header.duerr')}</i>}</div></span></div>
        <main className="workspace">{children}</main>

        {helpOpen && <HelpDrawer onClose={() => setHelpOpen(false)} />}
        {connectionOpen && <ConnectionDrawer context={context} gateways={gateways} health={systemHealth} error={error} loading={loading} onRefresh={refresh} onClose={() => setConnectionOpen(false)} />}
      </div>
    </DeploymentContextState.Provider>
  )
}
