import { AlertTriangle, Eye, Flame, Image as ImageIcon, Info, Layers3 } from 'lucide-react'
import { useState } from 'react'
import type { Inspection } from '../types'

type ViewMode = 'overlay' | 'original' | 'heatmap'

export function EvidenceViewer({ inspection, compact = false }: { inspection: Inspection; compact?: boolean }) {
  const [mode, setMode] = useState<ViewMode>('overlay')
  const [opacity, setOpacity] = useState(64)
  const [imageFailed, setImageFailed] = useState(false)
  const hasHeatmap = Boolean(inspection.image.heatmapUrl)
  const activeMode = hasHeatmap ? mode : 'original'

  return (
    <section className={`evidence-viewer ${compact ? 'compact' : ''}`} aria-label="视觉证据">
      <div className="viewer-toolbar">
        <div className="segmented-control" aria-label="图像显示模式">
          <button className={activeMode === 'original' ? 'active' : ''} onClick={() => setMode('original')}>
            <ImageIcon size={14} />原图
          </button>
          <button className={activeMode === 'overlay' ? 'active' : ''} onClick={() => setMode('overlay')} disabled={!hasHeatmap}>
            <Layers3 size={14} />叠加
          </button>
          <button className={activeMode === 'heatmap' ? 'active' : ''} onClick={() => setMode('heatmap')} disabled={!hasHeatmap}>
            <Flame size={14} />热力图
          </button>
        </div>
        {hasHeatmap && activeMode === 'overlay' && (
          <label className="opacity-control">
            <Eye size={15} aria-hidden="true" />
            <span>热力图透明度</span>
            <input
              aria-label="热力图透明度"
              type="range"
              min="0"
              max="100"
              value={opacity}
              onChange={(event) => setOpacity(Number(event.target.value))}
            />
            <output>{opacity}%</output>
          </label>
        )}
      </div>

      <div className="viewer-onboarding"><Info size={15} /><span><strong>怎么看：</strong>先看“原图”，再切到“叠加”确认颜色集中在哪里。颜色越暖，表示模型越关注；它不是缺陷结论。</span></div>

      <div className={`image-stage mode-${activeMode}`}>
        {!imageFailed && <img className="original-layer" src={inspection.image.originalUrl} alt={`${inspection.image.filename} 的原始检测图像`} loading="eager" decoding="async" onError={() => setImageFailed(true)} />}
        {!imageFailed && hasHeatmap && activeMode !== 'original' && (
          <img
            className="heatmap-layer"
            src={inspection.image.heatmapUrl}
            alt="模型生成的异常区域热力图"
            decoding="async"
            style={{ opacity: activeMode === 'heatmap' ? 1 : opacity / 100 }}
          />
        )}
        {imageFailed && <div className="image-error-state" role="alert"><AlertTriangle size={26} /><strong>图片暂时无法显示</strong><span>原始证据仍保留在系统中。请刷新页面；若仍失败，请在连接检查中确认图片存储服务。</span></div>}
        <div className="stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
        <div className="image-stamp"><span>证据 · 只读</span><code>{inspection.image.width} × {inspection.image.height}</code></div>
        {!hasHeatmap && (
          <div className="no-heatmap-notice">本次未生成热力图 · 不得自动放行</div>
        )}
      </div>
      <div className="viewer-caption">
        <span><i className="legend-cold" />低响应</span>
        <span><i className="legend-hot" />高响应</span>
        <p>暖色 = 模型更关注；最终结论必须由人工记录。</p>
      </div>
    </section>
  )
}
