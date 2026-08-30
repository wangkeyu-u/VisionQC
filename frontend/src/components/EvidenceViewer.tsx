import { AlertTriangle, Eye, Flame, Image as ImageIcon, Info, Layers3 } from 'lucide-react'
import { useState } from 'react'
import type { Inspection } from '../types'
import { useI18n } from '../hooks/useI18n'

type ViewMode = 'overlay' | 'original' | 'heatmap'

export function EvidenceViewer({ inspection, compact = false }: { inspection: Inspection; compact?: boolean }) {
  const { t, language } = useI18n()
  const [mode, setMode] = useState<ViewMode>('overlay')
  const [opacity, setOpacity] = useState(64)
  const [imageFailed, setImageFailed] = useState(false)
  const hasHeatmap = Boolean(inspection.image.heatmapUrl)
  const activeMode = hasHeatmap ? mode : 'original'
  return <section className={`evidence-viewer ${compact ? 'compact' : ''}`} aria-label={t('inspection.kicker')}>
    <div className="viewer-toolbar"><div className="segmented-control" aria-label={t('inspection.kicker')}>
      <button className={activeMode === 'original' ? 'active' : ''} onClick={() => setMode('original')}><ImageIcon size={14} />{t('inspection.original')}</button>
      <button className={activeMode === 'overlay' ? 'active' : ''} onClick={() => setMode('overlay')} disabled={!hasHeatmap}><Layers3 size={14} />{t('inspection.overlay')}</button>
      <button className={activeMode === 'heatmap' ? 'active' : ''} onClick={() => setMode('heatmap')} disabled={!hasHeatmap}><Flame size={14} />{t('inspection.heatmap')}</button>
    </div>{hasHeatmap && activeMode === 'overlay' && <label className="opacity-control"><Eye size={15} /><span>{t('inspection.opacity')}</span><input aria-label={t('inspection.opacity')} type="range" min="0" max="100" value={opacity} onChange={(event) => setOpacity(Number(event.target.value))} /><output>{opacity}%</output></label>}</div>
    <div className="viewer-onboarding"><Info size={15} /><span><strong>{t('inspection.howTo')}{language === 'zh' ? '：' : ': '}</strong>{t('inspection.howToBody')}</span></div>
    <div className={`image-stage mode-${activeMode}`}>
      {!imageFailed && <img className="original-layer" src={inspection.image.originalUrl} alt={`${inspection.image.filename} ${t('inspection.original')}`} loading="eager" decoding="async" onError={() => setImageFailed(true)} />}
      {!imageFailed && hasHeatmap && activeMode !== 'original' && <img className="heatmap-layer" src={inspection.image.heatmapUrl} alt={t('inspection.heatmap')} decoding="async" style={{ opacity: activeMode === 'heatmap' ? 1 : opacity / 100 }} />}
      {imageFailed && <div className="image-error-state" role="alert"><AlertTriangle size={26} /><strong>{t('inspection.imageError')}</strong><span>{t('inspection.imageErrorBody')}</span></div>}
      <div className="stage-corners" aria-hidden="true"><i /><i /><i /><i /></div><div className="image-stamp"><span>{t('inspection.kicker')}</span><code>{inspection.image.width} × {inspection.image.height}</code></div>{!hasHeatmap && <div className="no-heatmap-notice">{t('header.synthetic')}</div>}
    </div>
    <div className="viewer-caption"><span><i className="legend-cold" />{t('inspection.original')}</span><span><i className="legend-hot" />{t('inspection.heatmap')}</span><p>{t('inspection.boundaryBody')}</p></div>
  </section>
}
