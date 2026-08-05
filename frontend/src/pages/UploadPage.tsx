import { useEffect, useMemo, useState } from 'react'
import { useLocation } from 'wouter'
import {
  ArrowRight,
  CheckCircle2,
  FileImage,
  ImagePlus,
  Info,
  RotateCw,
  ShieldCheck,
  UploadCloud,
  X,
} from 'lucide-react'
import { visionQcApi } from '../api/visionQc'
import { ApiError } from '../api/client'
import { useDeploymentContext } from '../components/AppShell'
import type { Inspection } from '../types'
import { formatDateTime, formatScore, makeIdempotencyKey } from '../utils'
import { StatusBadge } from '../components/StatusBadge'
import { LoadingState } from '../components/Feedback'

const nowLocal = () => {
  const date = new Date(Date.now() - new Date().getTimezoneOffset() * 60_000)
  return date.toISOString().slice(0, 16)
}

export function UploadPage() {
  const [, navigate] = useLocation()
  const { context: tenantContext } = useDeploymentContext()
  const activeDeployment = tenantContext?.currentDeployment
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<Inspection[] | null>(null)
  const [form, setForm] = useState({
    productCode: '',
    productRevision: '',
    batchNo: '',
    station: '',
    capturedAt: nowLocal(),
  })

  useEffect(() => {
    if (!activeDeployment) return
    const product = activeDeployment.products[0]
    const station = activeDeployment.stations[0]
    setForm((current) => ({
      ...current,
      productCode: product?.code ?? '',
      productRevision: product?.revision ?? '',
      batchNo: `${activeDeployment.tenantId.toUpperCase()}-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-01`,
      station: station?.code ?? '',
    }))
  }, [activeDeployment?.packKey])

  useEffect(() => {
    visionQcApi.listRecentInspections().then(setRecent).catch(() => setRecent([]))
  }, [])

  useEffect(() => () => {
    if (preview?.startsWith('blob:')) URL.revokeObjectURL(preview)
  }, [preview])

  const fileError = useMemo(() => {
    if (!file) return null
    if (!['image/jpeg', 'image/png'].includes(file.type)) return '仅支持 JPEG 或 PNG 图片。'
    if (file.size > 20 * 1024 * 1024) return '文件超过 20 MB 上限。'
    return null
  }, [file])

  function acceptFile(nextFile: File, demoPreview?: string) {
    setError(null)
    setFile(nextFile)
    setPreview(demoPreview ?? URL.createObjectURL(nextFile))
  }

  async function loadDemo() {
    const encoded = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAuUlEQVR4nO3aqw1CARAF0XkTOiF5dSBpgQaQVICkAiQN0AIOasDQDh4c30zgyBX3brJ2h8v5SJnESZzESZzESZzESZzESZzESZzESZzETT5fOZsvbianw/7htB+7wHK1fscSy7vY3XbzKxeQOImTOImTOImTOImTuMnnK8dx+sI0iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iRv+7zZfJnESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ES57cXeNYV4wANFLwAsE0AAAAASUVORK5CYII='
    const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))
    const demo = new File([bytes], 'TR_AX14_B240804_demo.png', { type: 'image/png' })
    acceptFile(demo)
    if (activeDeployment) {
      setForm((current) => ({
        ...current,
        productCode: activeDeployment.products[0]?.code ?? current.productCode,
        productRevision: activeDeployment.products[0]?.revision ?? current.productRevision,
        station: activeDeployment.stations[0]?.code ?? current.station,
        batchNo: `${activeDeployment.tenantId.toUpperCase()}-DEMO-01`,
      }))
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!file || fileError) {
      setError(fileError ?? '请先选择一张待检图片。')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      const result = await visionQcApi.createInspection({
        ...form,
        file,
        capturedAt: new Date(form.capturedAt).toISOString(),
        idempotencyKey: makeIdempotencyKey(),
        fieldMapping: activeDeployment?.fieldMapping,
        source: 'Web manual upload',
      })
      navigate(`/inspections/${result.inspectionId}`)
    } catch (caught) {
      const apiError = caught instanceof ApiError ? caught : undefined
      setError(apiError ? `${apiError.message} ${apiError.nextStep ?? ''}（${apiError.correlationId ?? '无关联 ID'}）` : '上传失败，请检查网络后重试。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page upload-page">
      <div className="page-heading">
        <div><span className="page-kicker">检测接收 · Deployment Pack 感知</span><h1>接收新的检测样本</h1><p>提交原始证据与生产上下文。系统将异步完成异常检测，并按当前部署包的策略安全路由。</p></div>
        <div className="shift-summary"><span>{tenantContext?.tenant.name ?? '部署上下文'}</span><strong>{activeDeployment?.packKey ?? '读取中…'}</strong><small>{activeDeployment?.inputMode === 'folder_watch' ? '文件夹监听接入' : 'API 手动接入'} · 当前策略生效</small></div>
      </div>

      <div className="upload-layout">
        <form className="panel upload-panel" onSubmit={submit}>
          <div className="panel-heading"><div><span>01</span><h2>原始图像</h2></div><button type="button" className="text-button" onClick={() => void loadDemo()}><RotateCw size={14} />载入演示样本</button></div>
          <div
            className={`drop-zone ${isDragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
            onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setIsDragging(false)
              const dropped = event.dataTransfer.files[0]
              if (dropped) acceptFile(dropped)
            }}
          >
            {file && preview ? (
              <>
                <img src={preview} alt="待上传图像预览" />
                <div className="file-ticket">
                  <FileImage size={20} />
                  <span><strong>{file.name}</strong><small>{Math.max(file.size / 1024, 0.1).toFixed(1)} KB · {file.type || '未知类型'}</small></span>
                  <button type="button" aria-label="移除图片" onClick={() => { setFile(null); setPreview(null) }}><X size={16} /></button>
                </div>
              </>
            ) : (
              <label>
                <div className="drop-icon"><ImagePlus size={26} /></div>
                <strong>拖入产品图像，或点击选择</strong>
                <span>JPEG / PNG · 最大 20 MB · 单张图像</span>
                <input type="file" accept="image/jpeg,image/png" onChange={(event) => { const selected = event.target.files?.[0]; if (selected) acceptFile(selected) }} />
              </label>
            )}
          </div>
          {fileError && <div className="inline-error" role="alert">{fileError}</div>}

          <div className="panel-heading context-heading"><div><span>02</span><h2>生产上下文</h2></div><small><i />字段将写入不可覆盖的证据记录</small></div>
          <div className="form-grid">
            <label><span>{activeDeployment?.fieldLabels.product_code ?? '产品字段'} <b>*</b></span><select value={form.productCode} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, productCode: event.target.value })}>{activeDeployment?.products.map((product) => <option key={product.code} value={product.code}>{product.code} · {product.displayName}</option>) ?? <option value="">等待部署包…</option>}</select></label>
            <label><span>{activeDeployment?.fieldLabels.product_revision ?? '产品版本'} <b>*</b></span><input value={form.productRevision} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, productRevision: event.target.value })} /></label>
            <label><span>{activeDeployment?.fieldLabels.batch_no ?? '批次号'} <b>*</b></span><input value={form.batchNo} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, batchNo: event.target.value })} /></label>
            <label><span>{activeDeployment?.fieldLabels.station_code ?? '工位'} <b>*</b></span><select value={form.station} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, station: event.target.value })}>{activeDeployment?.stations.map((station) => <option key={station.code} value={station.code}>{station.code} · {station.displayName}</option>) ?? <option value="">等待部署包…</option>}</select></label>
            <label className="full"><span>{activeDeployment?.fieldLabels.captured_at ?? '采集时间'} <b>*</b></span><input type="datetime-local" value={form.capturedAt} required disabled={!activeDeployment} onChange={(event) => setForm({ ...form, capturedAt: event.target.value })} /></label>
          </div>

          {error && <div className="submission-error" role="alert"><Info size={17} /><span>{error}</span></div>}

          <div className="submission-bar">
            <div><ShieldCheck size={18} /><span><strong>安全路由已启用</strong><small>模型或策略不可用时将进入人工处理，不会自动放行。</small></span></div>
            <button className="primary-button" disabled={submitting || !activeDeployment}>{submitting ? <><UploadCloud className="pulse" size={17} />正在创建…</> : !activeDeployment ? <>等待部署包<ArrowRight size={17} /></> : <>创建检测任务<ArrowRight size={17} /></>}</button>
          </div>
        </form>

        <aside className="panel recent-panel">
          <div className="panel-heading"><div><span>最近记录</span><h2>最近检测</h2></div><small className="live-indicator"><i />实时</small></div>
          {!recent ? <LoadingState label="读取最近检测…" /> : (
            <div className="recent-list">
              {recent.map((inspection) => (
                <button key={inspection.id} onClick={() => navigate(`/inspections/${inspection.id}`)}>
                  <img src={inspection.image.originalUrl} alt="" />
                  <span className="recent-main"><strong>{inspection.context.batchNo}</strong><small>{inspection.id} · {formatDateTime(inspection.updatedAt)}</small><StatusBadge status={inspection.status} size="sm" /></span>
                  <span className="recent-score"><small>异常分数</small><strong>{formatScore(inspection.inference?.score)}</strong><ArrowRight size={14} /></span>
                </button>
              ))}
            </div>
          )}
          <div className="mock-disclosure"><Info size={16} /><p><strong>演示环境</strong> 当前图像、MES 与 QMS 均为模拟数据，不代表真实产线效果。</p></div>
          <div className="ingest-checks">
            <span><CheckCircle2 size={15} />格式与像素数校验</span>
            <span><CheckCircle2 size={15} />租户内幂等检查</span>
            <span><CheckCircle2 size={15} />SHA-256 证据指纹</span>
          </div>
        </aside>
      </div>
    </div>
  )
}
