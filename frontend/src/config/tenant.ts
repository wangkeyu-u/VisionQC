import { createContext, createElement, useContext, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import type { DeploymentPack } from '../types'

export type Language = 'zh' | 'en'
export type IndustryId = 'electronics' | 'packaging' | 'automotive-paint'
export type CaptureSource = 'example' | 'folder' | 'camera'
export type ProcessingMode = 'local' | 'authorized-upload'
export type ConnectorMode = 'mock' | 'configured'
export type CornerStyle = 'crisp' | 'soft' | 'round'
export type Density = 'comfortable' | 'compact'

export interface LocalizedTerm {
  zh: string
  en: string
}

export interface IndustryPack {
  id: IndustryId
  name: LocalizedTerm
  description: LocalizedTerm
  terms: {
    item: LocalizedTerm
    batch: LocalizedTerm
    station: LocalizedTerm
    qualityEvent: LocalizedTerm
    rework: LocalizedTerm
    sample: LocalizedTerm
    capture: LocalizedTerm
  }
  example: {
    productCode: string
    productName: LocalizedTerm
    stationCode: string
    stationName: LocalizedTerm
    batchPrefix: string
    metadata: Array<{ label: LocalizedTerm; value: string }>
  }
  colors: { primary: string; accent: string; wash: string }
}

export interface TenantBranding {
  displayName: string
  siteName: string
  logoUrl: string | null
  primaryColor: string
  accentColor: string
  cornerStyle: CornerStyle
  density: Density
}

export interface PrivacySettings {
  processingMode: ProcessingMode
  uploadAuthorized: boolean
  retentionDays: number
  deleteAfterUpload: boolean
}

export interface ConnectorSettings {
  mode: ConnectorMode
  mes: string
  qms: string
  gateway: string
  lastTestedAt: string | null
  testStatus: 'idle' | 'passed' | 'failed'
}

export interface RiskSettings {
  reviewThreshold: number
  holdThreshold: number
  hardSafetyRules: boolean
}

export interface RuntimeTenantConfig {
  language: Language
  industry: IndustryId
  branding: TenantBranding
  privacy: PrivacySettings
  connectors: ConnectorSettings
  risk: RiskSettings
  setupComplete: boolean
}

export const industryPacks: Record<IndustryId, IndustryPack> = {
  electronics: {
    id: 'electronics',
    name: { zh: '电子装配', en: 'Electronics assembly' },
    description: { zh: '适合元件、连接器和精密装配件的外观检查。', en: 'For visual checks on components, connectors, and precision assemblies.' },
    terms: {
      item: { zh: '产品', en: 'Product' },
      batch: { zh: '批次', en: 'Batch' },
      station: { zh: '工位', en: 'Station' },
      qualityEvent: { zh: '质量事件', en: 'Quality event' },
      rework: { zh: '返工', en: 'Rework' },
      sample: { zh: '元件合成样本', en: 'Synthetic component sample' },
      capture: { zh: '采集图片', en: 'Captured image' },
    },
    example: {
      productCode: 'TRANSISTOR-DEMO',
      productName: { zh: '电子元件', en: 'Electronic component' },
      stationCode: 'EOL-01',
      stationName: { zh: '终检工位', en: 'End-of-line inspection' },
      batchPrefix: 'ELEC',
      metadata: [
        { label: { zh: '封装类型', en: 'Package' }, value: 'TO-92' },
        { label: { zh: '视角', en: 'View' }, value: 'Top / lead' },
      ],
    },
    colors: { primary: '#2f6c52', accent: '#d5a348', wash: '#eaf3ed' },
  },
  packaging: {
    id: 'packaging',
    name: { zh: '包装', en: 'Packaging' },
    description: { zh: '适合标签、封口、印刷和包装完整性检查。', en: 'For label, seal, print, and packaging integrity checks.' },
    terms: {
      item: { zh: '包装件', en: 'Pack' },
      batch: { zh: '生产批', en: 'Production lot' },
      station: { zh: '检验点', en: 'Inspection point' },
      qualityEvent: { zh: '质量事件', en: 'Quality event' },
      rework: { zh: '返修', en: 'Rework' },
      sample: { zh: '包装合成样本', en: 'Synthetic pack sample' },
      capture: { zh: '采集图片', en: 'Captured image' },
    },
    example: {
      productCode: 'PACK-SEAL-DEMO',
      productName: { zh: '密封包装件', en: 'Sealed package' },
      stationCode: 'PACK-03',
      stationName: { zh: '封口检查', en: 'Seal inspection' },
      batchPrefix: 'PACK',
      metadata: [
        { label: { zh: '包装规格', en: 'Format' }, value: '250 ml' },
        { label: { zh: '印刷版本', en: 'Print revision' }, value: 'R2' },
      ],
    },
    colors: { primary: '#286b78', accent: '#e19a55', wash: '#eaf4f5' },
  },
  'automotive-paint': {
    id: 'automotive-paint',
    name: { zh: '汽车涂装', en: 'Automotive paint' },
    description: { zh: '适合车身表面、喷涂工艺和漆面外观检查。', en: 'For body-surface, paint-process, and finish appearance checks.' },
    terms: {
      item: { zh: '车身', en: 'Body' },
      batch: { zh: '生产批次', en: 'Production batch' },
      station: { zh: '喷涂工位', en: 'Paint station' },
      qualityEvent: { zh: '质量事件', en: 'Quality event' },
      rework: { zh: '返修', en: 'Rework' },
      sample: { zh: '涂装合成样本', en: 'Synthetic paint sample' },
      capture: { zh: '采集图片', en: 'Captured image' },
    },
    example: {
      productCode: 'PAINTED-BODY-DEMO',
      productName: { zh: '车身漆面', en: 'Painted body' },
      stationCode: 'PAINT-QC-01',
      stationName: { zh: '漆面终检', en: 'Paint finish check' },
      batchPrefix: 'PAINT',
      metadata: [
        { label: { zh: '车身编号', en: 'Body ID' }, value: 'BODY-DEMO-01' },
        { label: { zh: '漆色配方', en: 'Paint recipe' }, value: 'R-01' },
      ],
    },
    colors: { primary: '#6b4a38', accent: '#d59b55', wash: '#f4eee8' },
  },
}

/**
 * Keeps the UI coherent while tenant-config is still local-only. The backend
 * field mapping and model evidence remain untouched; a real adapter should
 * replace this preview with the tenant's signed deployment pack.
 */
export function applyRuntimeIndustryPack(deployment: DeploymentPack | undefined, pack: IndustryPack, enabled: boolean): DeploymentPack | undefined {
  if (!deployment || !enabled) return deployment
  const baseProduct = deployment.products[0]
  const baseStation = deployment.stations[0]
  return {
    ...deployment,
    id: `${deployment.id}:runtime:${pack.id}`,
    packKey: `runtime/${pack.id}`,
    displayName: `${pack.name.en} demo deployment`,
    products: [{
      ...(baseProduct ?? { revision: 'DEMO-R1', aliases: [] }),
      code: pack.example.productCode,
      displayName: pack.example.productName.zh,
      revision: baseProduct?.revision ?? 'DEMO-R1',
    }],
    stations: [{
      ...(baseStation ?? { description: '', cameraProfile: 'local-demo' }),
      code: pack.example.stationCode,
      displayName: pack.example.stationName.zh,
      description: pack.description.zh,
    }],
    fieldLabels: {
      ...deployment.fieldLabels,
      product_code: `${pack.terms.item.zh}编号`,
      product_revision: `${pack.terms.item.zh}版本`,
      batch_no: `${pack.terms.batch.zh}号`,
      station_code: pack.terms.station.zh,
      captured_at: pack.terms.capture.zh,
    },
    metadata: {
      ...deployment.metadata,
      runtimeIndustry: pack.id,
      runtimePreview: true,
    },
  }
}

export const DEFAULT_TENANT_CONFIG: RuntimeTenantConfig = {
  language: 'zh',
  industry: 'electronics',
  branding: {
    displayName: 'VisionQC Platform',
    siteName: 'Quality Workspace',
    logoUrl: null,
    primaryColor: '#2f6c52',
    accentColor: '#d5a348',
    cornerStyle: 'soft',
    density: 'comfortable',
  },
  privacy: {
    processingMode: 'local',
    uploadAuthorized: false,
    retentionDays: 30,
    deleteAfterUpload: false,
  },
  connectors: {
    mode: 'mock',
    mes: 'Mock MES',
    qms: 'Mock QMS',
    gateway: 'Simulated Gateway',
    lastTestedAt: null,
    testStatus: 'idle',
  },
  risk: {
    reviewThreshold: 0.4,
    holdThreshold: 0.8,
    hardSafetyRules: true,
  },
  setupComplete: false,
}

const STORAGE_KEY = 'visionqc.runtime-tenant.v1'

function browserStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

function readStoredConfig(): RuntimeTenantConfig {
  if (typeof window === 'undefined') return DEFAULT_TENANT_CONFIG
  try {
    const raw = browserStorage()?.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_TENANT_CONFIG
    const parsed = JSON.parse(raw) as Partial<RuntimeTenantConfig>
    return {
      ...DEFAULT_TENANT_CONFIG,
      ...parsed,
      branding: { ...DEFAULT_TENANT_CONFIG.branding, ...(parsed.branding ?? {}) },
      privacy: { ...DEFAULT_TENANT_CONFIG.privacy, ...(parsed.privacy ?? {}) },
      connectors: { ...DEFAULT_TENANT_CONFIG.connectors, ...(parsed.connectors ?? {}) },
      risk: { ...DEFAULT_TENANT_CONFIG.risk, ...(parsed.risk ?? {}) },
    }
  } catch {
    return DEFAULT_TENANT_CONFIG
  }
}

interface TenantConfigContextValue {
  config: RuntimeTenantConfig
  industryPack: IndustryPack
  updateConfig: (patch: Partial<RuntimeTenantConfig>) => void
  updateBranding: (patch: Partial<TenantBranding>) => void
  updatePrivacy: (patch: Partial<PrivacySettings>) => void
  updateConnectors: (patch: Partial<ConnectorSettings>) => void
  updateRisk: (patch: Partial<RiskSettings>) => void
  setLanguage: (language: Language) => void
  setIndustry: (industry: IndustryId) => void
  resetConfig: () => void
  themeStyle: CSSProperties
}

const TenantConfigContext = createContext<TenantConfigContextValue | undefined>(undefined)

function persist(next: RuntimeTenantConfig) {
  browserStorage()?.setItem(STORAGE_KEY, JSON.stringify(next))
}

export function TenantConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<RuntimeTenantConfig>(readStoredConfig)
  const updateConfig = (patch: Partial<RuntimeTenantConfig>) => setConfig((current) => {
    const next = { ...current, ...patch }
    persist(next)
    return next
  })
  const updateBranding = (patch: Partial<TenantBranding>) => updateConfig({ branding: { ...config.branding, ...patch } })
  const updatePrivacy = (patch: Partial<PrivacySettings>) => updateConfig({ privacy: { ...config.privacy, ...patch } })
  const updateConnectors = (patch: Partial<ConnectorSettings>) => updateConfig({ connectors: { ...config.connectors, ...patch } })
  const updateRisk = (patch: Partial<RiskSettings>) => updateConfig({ risk: { ...config.risk, ...patch } })
  const setLanguage = (language: Language) => updateConfig({ language })
  const setIndustry = (industry: IndustryId) => updateConfig({ industry })
  const resetConfig = () => {
    setConfig(DEFAULT_TENANT_CONFIG)
    browserStorage()?.removeItem(STORAGE_KEY)
  }
  const industryPack = industryPacks[config.industry]
  const themeStyle = useMemo(() => ({
    '--brand-primary': config.branding.primaryColor,
    '--brand-accent': config.branding.accentColor,
    '--industry-wash': industryPack.colors.wash,
    '--corner-radius': config.branding.cornerStyle === 'crisp' ? '5px' : config.branding.cornerStyle === 'round' ? '18px' : '10px',
    '--density-unit': config.branding.density === 'compact' ? '0.82' : '1',
  }) as CSSProperties, [config.branding, industryPack.colors.wash])

  return createElement(TenantConfigContext.Provider, { value: { config, industryPack, updateConfig, updateBranding, updatePrivacy, updateConnectors, updateRisk, setLanguage, setIndustry, resetConfig, themeStyle } }, children)
}

export function useTenantConfig(): TenantConfigContextValue {
  const value = useContext(TenantConfigContext)
  if (!value) throw new Error('useTenantConfig must be used inside TenantConfigProvider')
  return value
}

export function localized(term: LocalizedTerm, language: Language, bilingual = false): string {
  if (bilingual && language === 'zh') return `${term.zh}（${term.en}）`
  return language === 'en' ? term.en : term.zh
}

export { STORAGE_KEY }
