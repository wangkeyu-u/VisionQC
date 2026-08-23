import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Camera, CheckCircle2, FolderOpen, ImagePlus, LockKeyhole, ShieldCheck, UploadCloud, Wifi } from 'lucide-react'
import { useLocation } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { useDeploymentContext } from '../components/AppShell'
import type { GatewayStatus } from '../types'
import { makeIdempotencyKey } from '../utils'

type CaptureSource = 'example' | 'folder' | 'camera'

const sourceOptions: Array<{ id: CaptureSource; label: string; detail: string; icon: typeof ImagePlus }> = [
  { id: 'example', label: '示例图', detail: '立即体验完整闭环，不需要客户原图', icon: ImagePlus },
  { id: 'folder', label: '监控文件夹', detail: '现场 Gateway 会读取稳定的新文件', icon: FolderOpen },
  { id: 'camera', label: 'USB 相机', detail: '可选 OpenCV；没有硬件也能继续看示例', icon: Camera },
]

export function OnboardingPage() {
  const [, navigate] = useLocation()
  const { context } = useDeploymentContext()
  const deployment = context?.currentDeployment
  const [source, setSource] = useState<CaptureSource>('example')
  const [file, setFile] = useState<File | null>(null)
  const [selectedCount, setSelectedCount] = useState(0)
  const [consent, setConsent] = useState(false)
  const [gateways, setGateways] = useState<GatewayStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [fields, setFields] = useState({
    bodyId: '',
    station: '',
    line: 'LINE-01',
    modelVariant: 'SUV-DEMO',
    colorCode: 'C101',
    paintRecipe: 'R-01',
    shift: 'A',
  })

  useEffect(() => {
    if (!deployment) return
    setFields((current) => ({
      ...current,
      bodyId: `${deployment.tenantId.toUpperCase()}-BODY-DEMO-01`,
      station: deployment.stations[0]?.code ?? '',
    }))
  }, [deployment?.packKey])

  useEffect(() => {
    visionQcApi.listGatewayStatuses().then(setGateways).catch(() => setGateways([]))
  }, [context?.tenant.id])

  const currentGateway = useMemo(
    () => gateways.find((gateway) => gateway.tenantId === context?.tenant.id),
    [context?.tenant.id, gateways],
  )
  const isSynthetic = source === 'example'
  const localOnly = !consent && !isSynthetic

  function chooseSource(next: CaptureSource) {
    setSource(next)
    setFile(null)
    setSelectedCount(0)
    setError(null)
  }

  async function startDetection() {
    setError(null)
    if (isSynthetic) {
      navigate('/upload?demo=1')
      return
    }
    if (localOnly) {
      navigate('/operations')
      return
    }
    if (!file) {
      setError(source === 'folder' ? '请先选择一个监控文件夹中的图片。' : '请先用 USB 相机拍一张图，或选择一张相机图片。')
      return
    }
    if (!deployment) {
      setError('还没有读取到当前部署配置，请稍后再试。')
      return
    }
    setSubmitting(true)
    try {
      const result = await visionQcApi.createInspection({
        file,
        productCode: deployment.products[0]?.code ?? 'painted_body_panel',
        productRevision: deployment.products[0]?.revision ?? 'PILOT-0.1',
        batchNo: fields.bodyId,
        station: fields.station,
        capturedAt: new Date().toISOString(),
        idempotencyKey: makeIdempotencyKey(),
        fieldMapping: deployment.fieldMapping,
        source: source === 'camera' ? 'USB camera (operator consent)' : 'Folder upload (operator consent)',
        metadata: {
          body_id: fields.bodyId,
          workpiece_id: fields.bodyId,
          paint_shop: 'PAINT_SHOP_DEMO',
          booth_station: fields.station,
          line: fields.line,
          model_variant: fields.modelVariant,
          color_code: fields.colorCode,
          paint_recipe: fields.paintRecipe,
          shift: fields.shift,
          capture_mode: source === 'camera' ? 'USB_CAMERA' : 'FOLDER_UPLOAD',
          data_consent: true,
          data_purpose: '本地涂装质量检测与人工复核的网页演示',
        },
      })
      navigate(`/inspections/${result.inspectionId}`)
    } catch {
      setError('开始检测失败。请检查服务连接，或回到“示例图”继续体验。')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page onboarding-page">
      <div className="page-heading">
        <div><span className="page-kicker">新手向导 · Capture onboarding</span><h1>从一张图开始检测</h1><p>选择输入来源，完成预检，然后看异常证据、人工复核和模拟质量闭环。</p></div>
        <div className="onboarding-disclaimer">面向 Dürr 业务场景设计的独立作品集概念方案 / Independent portfolio concept; not commissioned or endorsed by Dürr.</div>
      </div>

      <ol className="flow-stepper" aria-label="新手检测流程">
        <li className="active"><span>1</span><strong>选输入</strong><small>示例图 / 文件夹 / USB 相机</small></li>
        <li><span>2</span><strong>做预检</strong><small>连接、格式、隐私</small></li>
        <li><span>3</span><strong>看闭环</strong><small>复核、事件、模拟 DXQ</small></li>
      </ol>

      <div className="onboarding-grid">
        <section className="panel onboarding-main">
          <div className="panel-heading"><div><span>第一步</span><h2>你手上的图片来自哪里？</h2></div><small>不用懂技术名词</small></div>
          <div className="source-choice-grid" role="radiogroup" aria-label="选择检测输入来源">
            {sourceOptions.map(({ id, label, detail, icon: Icon }) => (
              <button key={id} type="button" className={`source-choice ${source === id ? 'selected' : ''}`} onClick={() => chooseSource(id)} aria-pressed={source === id}>
                <Icon size={22} /><span><strong>{label}</strong><small>{detail}</small></span>{source === id && <CheckCircle2 size={17} />}
              </button>
            ))}
          </div>

          {source !== 'example' && (
            <div className="capture-input-card">
              <label className="capture-file-label">
                {source === 'folder' ? <FolderOpen size={20} /> : <Camera size={20} />}
                <span><strong>{source === 'folder' ? '选择文件夹中的一张代表图' : '调用 USB 相机或选择一张相机图'}</strong><small>{source === 'folder' ? '现场文件夹由 Edge Gateway 按稳定文件规则持续监控；这里用一张图做网页预检。' : '如果浏览器或电脑没有相机，系统会告诉你，不会让流程卡死。'}</small></span>
                <input type="file" accept="image/jpeg,image/png" multiple={source === 'folder'} capture={source === 'camera' ? 'environment' : undefined} {...({ webkitdirectory: source === 'folder' ? '' : undefined } as Record<string, string | undefined>)} onChange={(event) => { const files = Array.from(event.target.files ?? []); setSelectedCount(files.length); setFile(files[0] ?? null); setError(null) }} />
              </label>
              {file && <div className="selected-file"><CheckCircle2 size={16} /><span>{file.name}</span><small>{selectedCount > 1 ? `已选 ${selectedCount} 张，将先演示第一张` : '已准备好'}</small></div>}
            </div>
          )}

          <div className="panel-heading context-heading"><div><span>业务上下文</span><h2>车身数字质量档案的基本信息</h2></div><small>提交后写入只读证据</small></div>
          <div className="form-grid onboarding-form-grid">
            <label><span>车身/工件号 <b>*</b></span><input value={fields.bodyId} onChange={(event) => setFields({ ...fields, bodyId: event.target.value })} /></label>
            <label><span>涂装检查站 <b>*</b></span><select value={fields.station} onChange={(event) => setFields({ ...fields, station: event.target.value })}>{deployment?.stations.map((station) => <option key={station.code} value={station.code}>{station.code} · {station.displayName}</option>)}</select></label>
            <label><span>产线 / Line</span><input value={fields.line} onChange={(event) => setFields({ ...fields, line: event.target.value })} /></label>
            <label><span>车型 / Model variant</span><input value={fields.modelVariant} onChange={(event) => setFields({ ...fields, modelVariant: event.target.value })} /></label>
            <label><span>车漆颜色 / Color code</span><input value={fields.colorCode} onChange={(event) => setFields({ ...fields, colorCode: event.target.value })} /></label>
            <label><span>涂料配方 / Paint recipe</span><input value={fields.paintRecipe} onChange={(event) => setFields({ ...fields, paintRecipe: event.target.value })} /></label>
            <label><span>班次 / Shift</span><select value={fields.shift} onChange={(event) => setFields({ ...fields, shift: event.target.value })}><option>A</option><option>B</option><option>C</option></select></label>
          </div>

          <div className="privacy-consent-card">
            <div className="privacy-icon"><LockKeyhole size={19} /></div>
            <div><strong>默认本地处理，不上传客户原图</strong><p>示例图是合成演示证据；文件夹/USB 相机的客户原图只有在你明确勾选同意后，才会发送给网页演示服务。用途：{currentGateway?.dataPurpose ?? '本地涂装质量检测与人工复核'}；保留：{currentGateway?.retentionDays ?? 30} 天；删除：在现场 Gateway 的本地队列中按保留策略清理。</p><label className="consent-check"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>我明确同意将这张原图发送给 VisionQC 演示服务，仅用于本次质量流程演示。</span></label></div>
          </div>

          {error && <div className="submission-error" role="alert"><ShieldCheck size={17} /><span>{error}</span></div>}
          <div className="submission-bar onboarding-submit-bar"><div><ShieldCheck size={18} /><span><strong>{isSynthetic ? '合成演示安全' : consent ? '已记录发送同意' : '仍保持本地处理'}</strong><small>{isSynthetic ? '不会冒充生产或客户准确率证据。' : consent ? '原图会进入演示服务，并留下用途与幂等记录。' : '未勾选同意时不会从网页上传客户原图。'}</small></span></div><button className="primary-button" onClick={() => void startDetection()} disabled={submitting}>{submitting ? '正在创建检测…' : isSynthetic ? <>使用示例图开始<ArrowRight size={17} /></> : consent ? <>开始检测<ArrowRight size={17} /></> : <>查看本地 Gateway<ArrowRight size={17} /></>}</button></div>
        </section>

        <aside className="onboarding-side">
          <section className="panel preflight-card">
            <div className="panel-heading"><div><span>第二步</span><h2>开始前预检</h2></div><Wifi size={18} /></div>
            <ul className="preflight-list">
              <li className={deployment ? 'passed' : 'pending'}><CheckCircle2 size={16} /><span><strong>当前部署配置</strong><small>{deployment?.displayName ?? '正在读取…'}</small></span><b>{deployment ? '通过' : '等待'}</b></li>
              <li className={currentGateway?.status === 'ONLINE' ? 'passed' : 'pending'}><Wifi size={16} /><span><strong>现场接入程序</strong><small>{currentGateway ? `${currentGateway.gatewayId} · ${currentGateway.status}` : '示例图不依赖现场设备'}</small></span><b>{currentGateway?.status === 'ONLINE' ? '在线' : isSynthetic ? '可跳过' : '待检查'}</b></li>
              <li className="passed"><ShieldCheck size={16} /><span><strong>自动放行保护</strong><small>异常、OOD、坏图和模糊图都会安全降级到人工复核。</small></span><b>启用</b></li>
              <li className="passed"><LockKeyhole size={16} /><span><strong>数据发送状态</strong><small>{isSynthetic ? 'DEMO_SYNTHETIC 合成证据' : consent ? '已明确同意发送原图' : '本地处理，不发送原图'}</small></span><b>{isSynthetic || consent ? '清楚' : '默认'}</b></li>
            </ul>
          </section>
          <section className="panel onboarding-path-card">
            <div className="panel-heading"><div><span>第三步</span><h2>你将看到什么</h2></div><UploadCloud size={18} /></div>
            <ol><li>边缘接入与质量门禁</li><li>异常分数、热力图与车身数字质量档案</li><li>人工复核决定与审计时间线</li><li>模拟 MES / QMS / <code>dxq_mock</code> 质量闭环</li></ol>
            <p>这不是官方 DXQ API，也不替代 Dürr DXQ；它是隔离的概念连接器，方便验证 FDE 交付边界。</p>
          </section>
        </aside>
      </div>
    </div>
  )
}
