import { useTenantConfig } from '../config/tenant'
import { translate, type MessageKey } from '../i18n'

export function useI18n() {
  const { config } = useTenantConfig()
  return {
    language: config.language,
    t: (key: MessageKey, vars?: Record<string, string | number>) => translate(config.language, key, vars),
  }
}
