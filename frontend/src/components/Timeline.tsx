import { Bot, Cable, Cpu, ShieldCheck, UserRoundCheck } from 'lucide-react'
import type { TimelineEvent } from '../types'
import { formatAuditActor, formatAuditDetail, formatAuditTitle, formatDateTime } from '../utils'

const iconMap = {
  model: Cpu,
  policy: ShieldCheck,
  human: UserRoundCheck,
  connector: Cable,
  system: Bot,
}

export function Timeline({ events, compact = false }: { events: TimelineEvent[]; compact?: boolean }) {
  return (
    <ol className={`audit-timeline ${compact ? 'compact' : ''}`}>
      {[...events].reverse().map((event) => {
        const Icon = iconMap[event.kind]
        return (
          <li key={event.id}>
            <div className={`timeline-icon ${event.kind}`}><Icon size={16} /></div>
            <div className="timeline-copy">
              <div className="timeline-heading">
                <strong>{formatAuditTitle(event.title)}</strong>
                <time dateTime={event.occurredAt}>{formatDateTime(event.occurredAt, true)}</time>
              </div>
              <p>{formatAuditDetail(event.detail)}</p>
              <div className="timeline-meta"><span>{formatAuditActor(event.actor)}</span><details><summary>查看关联编号</summary><code>{event.correlationId}</code></details></div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
