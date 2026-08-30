import { useCallback, useEffect, useState } from 'react'
import { ArrowRight, FileWarning, RefreshCw } from 'lucide-react'
import { Link } from 'wouter'
import { visionQcApi } from '../api/visionQc'
import { ErrorState, LoadingState } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { useI18n } from '../hooks/useI18n'
import { decisionLabel, statusLabel } from '../i18n'
import type { IncidentSummary } from '../types'
import { formatDateTime, formatStation } from '../utils'

export function IncidentsPage() {
  const { t, language } = useI18n(); const [incidents, setIncidents] = useState<IncidentSummary[] | null>(null); const [error, setError] = useState<unknown>(null)
  const load = useCallback(async () => { try { setError(null); setIncidents(await visionQcApi.listIncidents()) } catch (caught) { setError(caught) } }, [])
  useEffect(() => { void load() }, [load])
  if (error) return <div className="page"><ErrorState error={error} onRetry={load} /></div>
  if (!incidents) return <div className="page"><LoadingState label={language === 'zh' ? '正在读取质量事件…' : 'Loading quality events…'} /></div>
  return <div className="page incidents-page"><div className="page-heading"><div><span className="page-kicker">{t('incidents.kicker')}</span><h1>{t('incidents.title')}</h1><p>{t('incidents.subtitle')}</p></div><button className="secondary-button" onClick={() => void load()}><RefreshCw size={15} />{t('common.refresh')}</button></div><div className="incident-list-panel work-panel"><div className="panel-heading"><div><FileWarning size={18} /><span className="eyebrow">01</span><h2>{t('incidents.current')}</h2></div><span className="panel-note">{incidents.length}</span></div>{incidents.length === 0 ? <div className="inline-empty"><FileWarning size={19} /><strong>{t('incidents.empty')}</strong><span>{t('incidents.emptyBody')}</span></div> : <div className="incident-list-table"><div className="incident-list-head"><span>{language === 'zh' ? '事件 / 批次' : 'Event / batch'}</span><span>{language === 'zh' ? '状态' : 'Status'}</span><span>{language === 'zh' ? '处置' : 'Disposition'}</span><span>{language === 'zh' ? '负责人' : 'Owner'}</span><span>{language === 'zh' ? '更新时间' : 'Updated'}</span><span /></div>{incidents.map((incident) => <Link className="incident-list-row" key={incident.id} href={`/incidents/${incident.id}`}><span><strong>{incident.id}</strong><small>{incident.productCode} · {incident.batchNo} · {formatStation(incident.station, language)}</small></span><StatusBadge status={incident.status} label={statusLabel(language, incident.status === 'ACTION_COMPLETED' ? 'VERIFYING' : incident.status)} size="sm" /><span>{decisionLabel(language, incident.disposition)}</span><span>{incident.owner ?? (language === 'zh' ? '待分配' : 'Unassigned')}</span><span>{formatDateTime(incident.updatedAt, true, language)}</span><ArrowRight size={15} /></Link>)}</div>}</div><div className="demo-disclosure"><span className="disclosure-label">{t('incidents.kicker')}</span><span>{t('incidents.boundary')}</span><Link href="/reviews">{t('nav.reviews')}<ArrowRight size={14} /></Link></div></div>
}
