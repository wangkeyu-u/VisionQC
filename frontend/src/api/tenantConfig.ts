/**
 * Integration seam for tenant configuration.
 *
 * Assumed future contract (not present in the current backend):
 * GET /api/v1/tenant-config -> RuntimeTenantConfig (or snake_case equivalent)
 * PUT /api/v1/tenant-config -> RuntimeTenantConfig, guarded by tenant admin auth
 * POST /api/v1/connectors/test -> { connector: string; status: 'PASSED'|'FAILED'; correlation_id: string }
 *
 * Until those endpoints exist, the UI persists this exact typed shape to localStorage
 * and labels connector results as simulated. The adapter intentionally does not send
 * branding, privacy, or connector mutations to the existing inspection API.
 */
import { DEFAULT_TENANT_CONFIG, type ConnectorSettings, type RuntimeTenantConfig } from '../config/tenant'

export interface TenantConfigAdapter {
  get(): Promise<RuntimeTenantConfig>
  save(config: RuntimeTenantConfig): Promise<RuntimeTenantConfig>
  testConnector(connector: ConnectorSettings): Promise<{ status: 'PASSED' | 'FAILED'; correlationId: string; simulated: boolean }>
}

/** Fixture used until the tenant-config and connector endpoints are available. */
export const MOCK_TENANT_CONFIG_FIXTURE: RuntimeTenantConfig = structuredClone(DEFAULT_TENANT_CONFIG)

export const mockTenantConfigAdapter: TenantConfigAdapter = {
  async get() {
    return structuredClone(MOCK_TENANT_CONFIG_FIXTURE)
  },
  async save(config) {
    return structuredClone(config)
  },
  async testConnector() {
    return { status: 'PASSED', correlationId: 'corr-MOCK-CONNECTOR-TEST', simulated: true }
  },
}

export const tenantConfigIntegrationAssumptions = {
  mode: 'local-mock',
  contractVersion: 'tenant-config.v1 (assumed)',
  backendAvailable: false,
  connectorWritesEnabled: false,
} as const
