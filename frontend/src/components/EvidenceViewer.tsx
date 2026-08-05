import { Eye, Flame, Image as ImageIcon, Layers3 } from 'lucide-react'
import { useState } from 'react'
import type { Inspection } from '../types'

type ViewMode = 'overlay' | 'original' | 'heatmap'

export function EvidenceViewer({ inspection, compact = false }: { inspection: Inspection; compact?: boolean }) {
  const [mode, setMode] = useState<ViewMode>('overlay')
  const [opacity, setOpacity] = useState(64)
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

      <div className={`image-stage mode-${activeMode}`}>
        <img className="original-layer" src={inspection.image.originalUrl} alt={`${inspection.image.filename} 原始检测图像`} />
        {hasHeatmap && activeMode !== 'original' && (
          <img
            className="heatmap-layer"
            src={inspection.image.heatmapUrl}
            alt="模型生成的异常区域热力图"
            style={{ opacity: activeMode === 'heatmap' ? 1 : opacity / 100 }}
          />
        )}
        <div className="stage-corners" aria-hidden="true"><i /><i /><i /><i /></div>
        <div className="image-stamp"><span>证据 · 只读</span><code>{inspection.image.width} × {inspection.image.height}</code></div>
        {!hasHeatmap && (
          <div className="no-heatmap-notice">本次未生成热力图 · 不得自动放行</div>
        )}
      </div>
      <div className="viewer-caption">
        <span><i className="legend-cold" />低响应</span>
        <span><i className="legend-hot" />高响应</span>
        <p>热力图仅表示模型关注区域，不代表缺陷类别或根因。</p>
      </div>
    </section>
  )
}
