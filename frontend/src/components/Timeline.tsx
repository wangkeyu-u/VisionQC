import { Bot, Cable, Cpu, ShieldCheck, UserRoundCheck } from 'lucide-react'
import type { TimelineEvent } from '../types'
import { formatAuditActor, formatAuditDetail, formatAuditTitle, formatDateTime } from '../utils'
import { useI18n } from '../hooks/useI18n'

const iconMap = { model: Cpu, policy: ShieldCheck, human: UserRoundCheck, connector: Cable, system: Bot }

export function Timeline({ events, compact = false }: { events: TimelineEvent[]; compact?: boolean }) {
  const { language } = useI18n()
  return <ol className={`audit-timeline ${compact ? 'compact' : ''}`}>{[...events].reverse().map((event) => { const Icon = iconMap[event.kind]; return <li key={event.id}><div className={`timeline-icon ${event.kind}`}><Icon size={16} /></div><div className="timeline-copy"><div className="timeline-heading"><strong>{formatAuditTitle(event.title, language)}</strong><time dateTime={event.occurredAt}>{formatDateTime(event.occurredAt, true, language)}</time></div><p>{formatAuditDetail(event.detail, language)}</p><div className="timeline-meta"><span>{formatAuditActor(event.actor, language)}</span><details><summary>{language === 'zh' ? '查看关联编号' : 'View correlation ID'}</summary><code>{event.correlationId}</code></details></div></div></li> })}</ol>
}
