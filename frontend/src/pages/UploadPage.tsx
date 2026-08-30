import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, CheckCircle2, FileImage, ImagePlus, Info, RotateCw, ShieldCheck, UploadCloud, X } from 'lucide-react'
import { useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ApiError } from '../api/client'
import { useDeploymentContext } from '../components/AppShell'
import { LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useI18n } from '../hooks/useI18n'
import { useTenantConfig, localized, type Language } from '../config/tenant'
import type { Inspection } from '../types'
import { formatDateTime, formatScore, formatStation, makeIdempotencyKey } from '../utils'

const nowLocal = () => { const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000); return date.toISOString().slice(0, 16) }
const hasHan = (value: string) => /[\u3400-\u9fff]/u.test(value)

export function UploadPage() {
  const [, navigate] = useLocation()
  const { context: tenantContext } = useDeploymentContext()
  const { t, language } = useI18n()
  const { config, industryPack } = useTenantConfig()
  const activeDeployment = tenantContext?.currentDeployment
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [isBlenderDemo, setIsBlenderDemo] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<Inspection[] | null>(null)
  const autoDemoLoaded = useRef(false)
  const [form, setForm] = useState({ productCode: '', productRevision: '', batchNo: '', station: '', capturedAt: nowLocal() })

  useEffect(() => {
    if (!activeDeployment) return
    const product = activeDeployment.products[0]; const station = activeDeployment.stations[0]
    const batchPrefix = config.setupComplete ? industryPack.example.batchPrefix : activeDeployment.tenantId.toUpperCase()
    setForm((current) => ({ ...current, productCode: product?.code ?? '', productRevision: product?.revision ?? '', batchNo: `${batchPrefix}-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-01`, station: station?.code ?? '' }))
  }, [activeDeployment?.packKey, config.setupComplete, industryPack.example.batchPrefix])
  useEffect(() => { visionQcApi.listRecentInspections().then(setRecent).catch(() => setRecent([])) }, [tenantContext?.tenant.id])
  useEffect(() => { if (!activeDeployment || autoDemoLoaded.current || new URLSearchParams(window.location.search).get('demo') !== '1') return; autoDemoLoaded.current = true; void loadDemo() }, [activeDeployment?.packKey])
  useEffect(() => () => { if (preview?.startsWith('blob:')) URL.revokeObjectURL(preview) }, [preview])

  const fileError = useMemo(() => { if (!file) return null; if (!['image/jpeg', 'image/png'].includes(file.type)) return t('error.fileType'); if (file.size > 20 * 1024 * 1024) return t('error.fileSize'); return null }, [file, t])
  function acceptFile(nextFile: File, demoPreview?: string, blenderDemo = false) { setError(null); setFile(nextFile); setPreview(demoPreview ?? URL.createObjectURL(nextFile)); setIsBlenderDemo(blenderDemo) }
  async function loadDemo() {
    let blob: Blob
    try { const response = await fetch('/mock/blender/transistor-bent-lead.png'); if (!response.ok) throw new Error('demo asset unavailable'); blob = await response.blob() } catch { blob = new Blob(['VisionQC sample'], { type: 'image/png' }) }
    const demo = new File([blob], 'visionqc-synthetic-sample.png', { type: 'image/png' })
    acceptFile(demo, '/mock/blender/transistor-bent-lead.png', true)
    if (activeDeployment) setForm((current) => ({ ...current, productCode: activeDeployment.products[0]?.code ?? current.productCode, productRevision: activeDeployment.products[0]?.revision ?? current.productRevision, station: activeDeployment.stations[0]?.code ?? current.station, batchNo: `${config.setupComplete ? industryPack.example.batchPrefix : activeDeployment.tenantId.toUpperCase()}-DEMO-01` }))
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!file || fileError) { setError(fileError ?? t('error.chooseImage')); return }
    setSubmitting(true); setError(null)
    try { const result = await visionQcApi.createInspection({ ...form, file, capturedAt: new Date(form.capturedAt).toISOString(), idempotencyKey: makeIdempotencyKey(), fieldMapping: activeDeployment?.fieldMapping, source: isBlenderDemo ? 'Blender synthetic demo' : 'Web manual upload' }); navigate(`/inspections/${result.inspectionId}`) } catch (caught) { const apiError = caught instanceof ApiError ? caught : undefined; setError(apiError ? `${apiError.message} ${apiError.nextStep ?? ''}` : t('error.upload')) } finally { setSubmitting(false) }
  }
  const fieldLabel = (key: string, zhFallback: string, enFallback: string) => {
    const backendLabel = activeDeployment?.fieldLabels[key]
    if (config.industry === 'electronics' && backendLabel && (language === 'zh' || !hasHan(backendLabel))) return backendLabel
    const glossaryTerm = key === 'batch_no' ? industryPack.terms.batch : key === 'station_code' ? industryPack.terms.station : key === 'captured_at' ? industryPack.terms.capture : industryPack.terms.item
    return language === 'zh' ? `${localized(glossaryTerm, language, true)}${zhFallback}` : enFallback
  }
  const displayProductName = (value: string) => language === 'en' && hasHan(value) ? industryPack.example.productName.en : value
  const displayStationName = (value: string) => language === 'en' && hasHan(value) ? industryPack.example.stationName.en : value
  const demoSuffix = language === 'zh' ? '（Blender）' : ' (Blender)'
  return <div className="page upload-page">
    <div className="page-heading"><div><span className="page-kicker">{t('upload.kicker')}</span><h1>{t('upload.title')}</h1><p>{t('upload.subtitle')}</p></div><div className="shift-summary"><span>{tenantContext?.tenant.name ?? t('header.tenant')}</span><strong>{localized(industryPack.name, language)}</strong><small>{t('header.simulation')} · {t('header.synthetic')}</small></div></div>
    <ol className="flow-stepper" aria-label={language === 'zh' ? '检测流程' : 'Inspection flow'}><li className="active"><span>1</span><strong>{t('upload.step1')}</strong><small>{t('upload.step1Hint')}</small></li><li><span>2</span><strong>{t('upload.step2')}</strong><small>{t('upload.step2Hint')}</small></li><li><span>3</span><strong>{t('upload.step3')}</strong><small>{t('upload.step3Hint')}</small></li></ol>
    <div className="upload-layout">
      <form className="panel upload-panel" onSubmit={submit}>
        <div className="panel-heading"><div><span className="step-chip">01</span><h2>{t('upload.chooseImage')}</h2></div><button type="button" className="secondary-button compact-button" onClick={() => void loadDemo()}><RotateCw size={14} />{t('upload.useExample')}{demoSuffix}</button></div>
        <div className={`drop-zone ${isDragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`} onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setIsDragging(false)} onDrop={(event) => { event.preventDefault(); setIsDragging(false); const dropped = event.dataTransfer.files[0]; if (dropped) acceptFile(dropped) }}>
          {file && preview ? <><img src={preview} alt={language === 'zh' ? '待上传图像预览' : 'Image preview before upload'} /><div className="file-ticket"><FileImage size={20} /><span><strong>{file.name}</strong><small>{Math.max(file.size / 1024, 0.1).toFixed(1)} KB · {file.type || 'unknown'}{isBlenderDemo ? ` · ${t('upload.synthetic')}` : ''}</small></span><button type="button" aria-label={t('upload.remove')} onClick={() => { setFile(null); setPreview(null); setIsBlenderDemo(false) }}><X size={16} /></button></div></> : <label><div className="drop-icon"><ImagePlus size={26} /></div><strong>{t('upload.drop')}</strong><span>{t('upload.fileTypes')}</span><input type="file" accept="image/jpeg,image/png" onChange={(event) => { const selected = event.target.files?.[0]; if (selected) acceptFile(selected) }} /></label>}
        </div>
        {fileError && <div className="inline-error" role="alert">{fileError}</div>}
        <div className="panel-heading context-heading"><div><span className="step-chip">02</span><h2>{t('upload.context')}</h2></div><small><i />{t('upload.readonly')}</small></div>
        <div className="form-grid"><label><span>{fieldLabel('product_code', '编号', 'Product code')} <b>*</b></span><select value={form.productCode} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, productCode: event.target.value })}>{activeDeployment?.products.map((product) => <option key={product.code} value={product.code}>{product.code} · {displayProductName(product.displayName)}</option>) ?? <option value="">{t('common.loading')}</option>}</select></label><label><span>{fieldLabel('product_revision', '版本', 'Revision')} <b>*</b></span><input value={form.productRevision} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, productRevision: event.target.value })} /></label><label><span>{fieldLabel('batch_no', '号', 'Batch number')} <b>*</b></span><input value={form.batchNo} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, batchNo: event.target.value })} /></label><label><span>{fieldLabel('station_code', '', 'Station')} <b>*</b></span><select value={form.station} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, station: event.target.value })}>{activeDeployment?.stations.map((station) => <option key={station.code} value={station.code}>{formatStation(station.code, language)} · {displayStationName(station.displayName)}</option>) ?? <option value="">{t('common.loading')}</option>}</select></label><label className="full"><span>{fieldLabel('captured_at', '', 'Captured at')} <b>*</b></span><input type="datetime-local" value={form.capturedAt} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, capturedAt: event.target.value })} /></label></div>
        {error && <div className="submission-error" role="alert"><Info size={17} /><span>{error}</span></div>}
        <div className="submission-bar"><div><ShieldCheck size={18} /><span><strong>{t('upload.localSafety')}</strong><small>{t('upload.localSafetyBody')}</small></span></div><button className="primary-button" disabled={submitting || !activeDeployment}>{submitting ? <><UploadCloud className="pulse" size={17} />{t('upload.uploading')}</> : !activeDeployment ? <>{t('upload.readingConfig')}<ArrowRight size={17} /></> : <>{t('upload.begin')}<ArrowRight size={17} /></>}</button></div>
      </form>
      <aside className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">{t('upload.recent')}</span><h2>{t('upload.recent')}</h2></div><small className="live-indicator"><i />{t('upload.autoUpdate')}</small></div>{!recent ? <LoadingState /> : <div className="recent-list">{recent.map((inspection) => <button key={inspection.id} onClick={() => navigate(`/inspections/${inspection.id}`)}><img src={inspection.image.originalUrl} alt="" /><span className="recent-main"><strong>{inspection.context.batchNo}</strong><small>{inspection.id} · {formatDateTime(inspection.updatedAt, false, language)}</small><StatusBadge status={inspection.status} size="sm" /></span><span className="recent-score"><small>{t('inspection.score')}</small><strong>{formatScore(inspection.inference?.score)}</strong><ArrowRight size={14} /></span></button>)}</div>}
        <div className="synthetic-source-card"><img src="/mock/blender/station-overview.png" alt={localized(industryPack.terms.sample, language)} /><div><strong>{t('upload.synthetic')}</strong><p>{t('upload.syntheticBody')}</p><small>{t('header.synthetic')} · {localized(industryPack.terms.capture, language, true)}</small></div></div><div className="mock-disclosure"><Info size={16} /><p><strong>{t('header.simulation')}</strong> · {t('upload.sourceNoteBody')}</p></div><div className="ingest-checks"><span><CheckCircle2 size={15} />{language === 'zh' ? '格式与像素数校验' : 'Format and pixel checks'}</span><span><CheckCircle2 size={15} />{language === 'zh' ? '租户内幂等检查' : 'Tenant idempotency check'}</span><span><CheckCircle2 size={15} />SHA-256 {language === 'zh' ? '证据指纹' : 'evidence fingerprint'}</span></div></aside>
    </div>
  </div>
}
