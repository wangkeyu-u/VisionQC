import { useEffect, useMemo, useRef, useState } from 'react'
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
  const [isBlenderDemo, setIsBlenderDemo] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<Inspection[] | null>(null)
  const autoDemoLoaded = useRef(false)
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

  useEffect(() => {
    if (!activeDeployment || autoDemoLoaded.current || new URLSearchParams(window.location.search).get('demo') !== '1') return
    autoDemoLoaded.current = true
    void loadDemo()
  }, [activeDeployment?.packKey])

  useEffect(() => () => {
    if (preview?.startsWith('blob:')) URL.revokeObjectURL(preview)
  }, [preview])

  const fileError = useMemo(() => {
    if (!file) return null
    if (!['image/jpeg', 'image/png'].includes(file.type)) return '仅支持 JPEG 或 PNG 图片。'
    if (file.size > 20 * 1024 * 1024) return '文件超过 20 MB 上限。'
    return null
  }, [file])

  function acceptFile(nextFile: File, demoPreview?: string, blenderDemo = false) {
    setError(null)
    setFile(nextFile)
    setPreview(demoPreview ?? URL.createObjectURL(nextFile))
    setIsBlenderDemo(blenderDemo)
  }

  async function loadDemo() {
    let blob: Blob
    try {
      const response = await fetch('/mock/blender/transistor-bent-lead.png')
      if (!response.ok) throw new Error('demo asset unavailable')
      blob = await response.blob()
    } catch {
      const encoded = 'iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAuUlEQVR4nO3aqw1CARAF0XkTOiF5dSBpgQaQVICkAiQN0AIOasDQDh4c30zgyBX3brJ2h8v5SJnESZzESZzESZzESZzESZzESZzESZzETT5fOZsvbianw/7htB+7wHK1fscSy7vY3XbzKxeQOImTOImTOImTOImTuMnnK8dx+sI0iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iRv+7zZfJnESJ3ESJ3ESJ3ESJ3ESJ3ESJ3ES57cXeNYV4wANFLwAsE0AAAAASUVORK5CYII='
      blob = new Blob([Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0))], { type: 'image/png' })
    }
    const demo = new File([blob], 'blender-transistor-bent-lead.png', { type: 'image/png' })
    acceptFile(demo, '/mock/blender/transistor-bent-lead.png', true)
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
        source: isBlenderDemo ? 'Blender synthetic demo' : 'Web manual upload',
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
        <div><span className="page-kicker">新建检测</span><h1>上传一张产品图片</h1><p>选择图片并核对批次信息。系统会指出可疑区域，再把需要确认的图片交给人工复核。</p></div>
        <div className="shift-summary"><span>{tenantContext?.tenant.name ?? '当前工厂'}</span><strong>{activeDeployment?.displayName ?? '正在读取产品配置…'}</strong><small>{activeDeployment?.inputMode === 'folder_watch' ? '现场文件夹已接入' : '网页上传已启用'} · 演示数据不会进入真实生产系统</small></div>
      </div>

      <ol className="flow-stepper" aria-label="检测流程">
        <li className="active"><span>1</span><strong>选择图片</strong><small>可使用内置演示样本</small></li>
        <li><span>2</span><strong>系统分析</strong><small>生成分数和可疑区域</small></li>
        <li><span>3</span><strong>人工确认</strong><small>决定合格或如何处置</small></li>
      </ol>

      <div className="upload-layout">
        <form className="panel upload-panel" onSubmit={submit}>
          <div className="panel-heading"><div><span>第 1 步</span><h2>选择产品图片</h2></div><button type="button" className="secondary-button compact-button" onClick={() => void loadDemo()}><RotateCw size={14} />使用演示图片（Blender）</button></div>
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
                  <span><strong>{file.name}</strong><small>{Math.max(file.size / 1024, 0.1).toFixed(1)} KB · {file.type || '未知类型'}{isBlenderDemo ? ' · Blender 合成样本' : ''}</small></span>
                  <button type="button" aria-label="移除图片" onClick={() => { setFile(null); setPreview(null); setIsBlenderDemo(false) }}><X size={16} /></button>
                </div>
              </>
            ) : (
              <label>
                <div className="drop-icon"><ImagePlus size={26} /></div>
                <strong>把图片拖到这里，或点击选择文件</strong>
                <span>支持 JPEG、PNG；每次一张，最大 20 MB</span>
                <input type="file" accept="image/jpeg,image/png" onChange={(event) => { const selected = event.target.files?.[0]; if (selected) acceptFile(selected) }} />
              </label>
            )}
          </div>
          {fileError && <div className="inline-error" role="alert">{fileError}</div>}

          <div className="panel-heading context-heading"><div><span>第 2 步</span><h2>核对产品和批次信息</h2></div><small><i />提交后会保存为只读记录</small></div>
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
            <button className="primary-button" disabled={submitting || !activeDeployment}>{submitting ? <><UploadCloud className="pulse" size={17} />正在上传并创建任务…</> : !activeDeployment ? <>正在读取产品配置<ArrowRight size={17} /></> : <>开始检测<ArrowRight size={17} /></>}</button>
          </div>
        </form>

        <aside className="panel recent-panel">
          <div className="panel-heading"><div><span>历史记录</span><h2>最近处理的图片</h2></div><small className="live-indicator"><i />自动更新</small></div>
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
          <div className="synthetic-source-card">
            <img src="/mock/blender/station-overview.png" alt="Blender 生成的工业视觉检测工位" />
            <div><strong>Blender 合成样本</strong><p>模型、工位、灯光、弯折引脚和像素掩码都可由项目脚本重新生成。</p><small>只验证系统流程，不计入模型效果，也不代表真实产线。</small></div>
          </div>
          <div className="mock-disclosure"><Info size={16} /><p><strong>这是演示环境</strong> MES、QMS 和内置图片均为模拟数据，不会修改真实工厂系统。</p></div>
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
