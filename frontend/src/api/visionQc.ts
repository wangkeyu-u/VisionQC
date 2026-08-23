import { apiRequest, apiRequestBlob, replaceAccessToken } from './client'
import type {
  CreateInspectionResponse,
  ExternalAction,
  Inspection,
  InspectionStatus,
  QualityIncident,
  ReviewReceipt,
  ReviewSubmission,
  ReviewTask,
  TimelineEvent,
  TimelineKind,
  DeploymentFieldMapping,
  DeploymentPack,
  GatewayStatus,
  IncidentSummary,
  ModelOpsStatus,
  OperationsSummary,
  SystemHealth,
  TenantContext,
} from '../types'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false'
const assetUrlCache = new Map<string, Promise<string>>()

export interface InspectionUpload {
  file: File
  productCode: string
  productRevision: string
  batchNo: string
  station: string
  capturedAt: string
  idempotencyKey: string
  fieldMapping?: DeploymentFieldMapping
  source?: string
  metadata?: Record<string, unknown>
}

interface RawDeploymentPack {
  id: string
  tenant_id: string
  version: string
  status: string
  model: Record<string, unknown>
  policy: Record<string, unknown>
  connectors: Record<string, unknown>
  manifest: RawDeploymentManifest
}

interface RawDeploymentManifest {
  pack_key: string
  version: string
  display_name: string
  input_mode: 'api_upload' | 'folder_watch'
  products: Array<{
    code: string
    display_name: string
    revision: string
    aliases: string[]
  }>
  stations: Array<{
    code: string
    display_name: string
    description: string
    camera_profile: string
  }>
  field_mapping: Record<string, string>
  field_labels: Record<string, string>
  model: Record<string, unknown>
  policy: Record<string, unknown>
  connectors: Record<string, unknown>
  metadata: Record<string, unknown>
}

interface RawTenantContext {
  tenant: { id: string; name: string; status: string }
  current_deployment: RawDeploymentPack | null
  available_tenants: Array<{ id: string; name: string; status: string }>
}

function mapDeployment(raw: RawDeploymentPack): DeploymentPack {
  const manifest = raw.manifest
  const model = manifest.model
  const policy = manifest.policy as {
    version: string
    default: { review_threshold: number; hold_threshold: number }
    overrides?: Array<Record<string, unknown>>
  }
  const connectors = manifest.connectors as {
    mes: Record<string, unknown>
    qms: Record<string, unknown>
    dxq_mock?: Record<string, unknown>
  }
  const mapConnector = (value: Record<string, unknown>) => ({
    displayName: String(value.display_name ?? 'Connector'),
    driver: String(value.driver ?? 'unknown'),
    contractVersion: String(value.contract_version ?? 'unknown'),
    endpoint: String(value.endpoint ?? 'not-configured'),
    payloadMapping: (value.payload_mapping ?? {}) as Record<string, string>,
    fixedFields: (value.fixed_fields ?? {}) as Record<string, unknown>,
    operations: (value.operations ?? []) as string[],
  })
  return {
    id: raw.id,
    tenantId: raw.tenant_id,
    version: raw.version,
    status: raw.status,
    packKey: manifest.pack_key,
    displayName: manifest.display_name,
    inputMode: manifest.input_mode,
    products: manifest.products.map((product) => ({
      code: product.code,
      displayName: product.display_name,
      revision: product.revision,
      aliases: product.aliases,
    })),
    stations: manifest.stations.map((station) => ({
      code: station.code,
      displayName: station.display_name,
      description: station.description,
      cameraProfile: station.camera_profile,
    })),
    fieldMapping: {
      productCode: String(manifest.field_mapping.product_code),
      productRevision: String(manifest.field_mapping.product_revision),
      batchNo: String(manifest.field_mapping.batch_no),
      stationCode: String(manifest.field_mapping.station_code),
      capturedAt: String(manifest.field_mapping.captured_at),
      source: String(manifest.field_mapping.source),
    },
    fieldLabels: manifest.field_labels,
    model: {
      id: String(model.id),
      version: String(model.version),
      featureBankVersion: String(model.feature_bank_version),
      adapter: String(model.adapter),
      runtime: String(model.runtime),
      device: String(model.device),
      packageUri: String(model.package_uri),
      packageSha256: typeof model.package_sha256 === 'string' ? model.package_sha256 : null,
      scoreSemantics: String(model.score_semantics),
      limitations: (model.limitations ?? []) as string[],
    },
    policy: {
      version: policy.version,
      default: {
        reviewThreshold: policy.default.review_threshold,
        holdThreshold: policy.default.hold_threshold,
      },
      overrides: (policy.overrides ?? []).map((override) => ({
        productCode: typeof override.product_code === 'string' ? override.product_code : null,
        stationCode: typeof override.station_code === 'string' ? override.station_code : null,
        reviewThreshold: Number(override.review_threshold),
        holdThreshold: Number(override.hold_threshold),
      })),
    },
    connectors: {
      mes: mapConnector(connectors.mes),
      qms: mapConnector(connectors.qms),
      dxqMock: connectors.dxq_mock ? mapConnector(connectors.dxq_mock) : undefined,
    },
    metadata: manifest.metadata,
  }
}

function normalizeTenantContext(raw: RawTenantContext | TenantContext): TenantContext {
  if ('currentDeployment' in raw) return raw as TenantContext
  const legacy = raw as RawTenantContext
  return {
    tenant: legacy.tenant,
    currentDeployment: legacy.current_deployment
      ? mapDeployment(legacy.current_deployment)
      : undefined,
    availableTenants: legacy.available_tenants,
  }
}

interface RawTimeline {
  occurred_at: string
  source: string
  action: string
  actor: string
  details: Record<string, unknown>
  correlation_id: string
}

interface RawImage {
  id: string
  kind: string
  sha256: string
  mime_type: string
  width: number
  height: number
}

interface RawInspection {
  inspection_id: string
  tenant_id: string
  status: InspectionStatus
  correlation_id: string
  context: {
    product_code: string
    product_revision?: string | null
    batch_no: string
    station_code: string
    captured_at: string
    source: string
    metadata?: Record<string, unknown>
  }
  images: RawImage[]
  model?: {
    score: number
    latency_ms: number
    model_id: string
    model_version: string
    feature_bank_version: string
    runtime_device: string
    semantic_defect_confirmed: boolean
  } | null
  policy?: {
    version: string
    decision: string
    reason: string
    snapshot: Record<string, unknown>
  } | null
  review_task_id?: string | null
  incident_id?: string | null
  failure_reason?: string | null
  quality_flags?: string[]
  idempotent_replay: boolean
  created_at: string
  updated_at: string
}

interface RawReviewTask {
  id: string
  inspection_id: string
  status: ReviewTask['status']
  assignee?: string | null
  version: number
  sla_at?: string | null
  priority: ReviewTask['priority']
  route: ReviewTask['route']
  batch_no: string
  product_code: string
  station_code: string
  score?: number | null
  thumbnail_asset_id?: string | null
  held: boolean
}

interface RawExternalAction {
  id: string
  connector: string
  operation: string
  status: string
  attempts: number
  external_reference?: string | null
  last_error?: string | null
  idempotency_key: string
  updated_at: string
}

interface RawIncident {
  id: string
  inspection_id: string
  status: string
  severity: QualityIncident['severity']
  created_at: string
  updated_at: string
  owner?: string | null
  disposition: QualityIncident['disposition']
  outcome?: string | null
  verification_record?: string | null
  batch_no: string
  product_code: string
  station_code: string
  evidence: {
    score: number
    model_version: string
    policy_version: string
    decision_actor: string
    decision_reason: string
  }
  external_actions: RawExternalAction[]
  timeline: RawTimeline[]
  correlation_id: string
}

interface RawGatewayStatus {
  tenant_id: string
  gateway_id: string
  gateway_version: string
  station_code: string
  status: GatewayStatus['status']
  reported_status: string
  queue_depth: number
  last_error?: string | null
  last_heartbeat_at: string
  last_upload_succeeded_at?: string | null
  last_upload_failed_at?: string | null
  upload_success_count: number
  upload_failure_count: number
  deployment_pack_key?: string | null
  deployment_pack_version?: string | null
  metrics: Record<string, unknown>
  upload_enabled?: boolean
  data_consent?: boolean
  data_purpose?: string
  retention_days?: number
  delete_after_upload?: boolean
  local_processing_default?: boolean
  camera_enabled?: boolean
  camera_index?: number
}

interface RawOperationsSummary {
  tenant_id: string
  generated_at: string
  window_hours: number
  inspections_24h: number
  route_counts: Record<string, number>
  review_backlog: number
  review_high_risk: number
  incident_counts: Record<string, number>
  gateways_total: number
  gateways_online: number
  gateway_online_rate?: number | null
  gateway_queue_depth: number
  upload_success_count: number
  upload_failure_count: number
}

interface RawIncidentSummary {
  id: string
  inspection_id: string
  status: string
  severity: string
  created_at: string
  updated_at: string
  owner?: string | null
  disposition: string
  batch_no: string
  product_code: string
  station_code: string
}

interface RawModelOpsStatus {
  tenant_id: string
  pack_key: string
  deployment_version: string
  deployment_status: string
  product_code: string
  model_id: string
  model_version: string
  feature_bank_version: string
  package_verified: boolean
  model_release_status: ModelOpsStatus['modelReleaseStatus']
  synthetic_smoke: boolean
  smoke_checks_passed: number
  smoke_checks_total: number
  test_samples: number
  mvtec_metrics_available: boolean
  calibration_constraints_satisfied: boolean
  report_generated_at: string
  evidence_source: string
  limitations: string[]
  release_recommendation: string[]
  qualification_status?: string
  model_package_sha256?: string | null
  evidence_package_sha256?: string | null
  gate_results?: Record<string, unknown>
  activation_allowed?: boolean
  dataset_source_type?: ModelOpsStatus['datasetSourceType']
  dataset_source_status?: ModelOpsStatus['datasetSourceStatus'] | null
  dataset_registration_id?: string | null
  dataset_fingerprint?: string | null
  report_status?: string
  customer_data_gate?: string
  risk_labels?: string[]
}

function isUiInspection(value: unknown): value is Inspection {
  return Boolean(value && typeof value === 'object' && 'id' in value && 'image' in value)
}

function timelineKind(item: RawTimeline): TimelineKind {
  const text = `${item.source} ${item.action} ${item.actor}`.toLowerCase()
  if (text.includes('model') || text.includes('inference')) return 'model'
  if (text.includes('policy')) return 'policy'
  if (text.includes('connector') || text.includes('external')) return 'connector'
  if (!text.includes('system')) return 'human'
  return 'system'
}

function normalizeTimeline(items: RawTimeline[]): TimelineEvent[] {
  return items.map((item, index) => ({
    id: `${item.occurred_at}-${index}`,
    occurredAt: item.occurred_at,
    title: item.action,
    detail: typeof item.details.reason === 'string'
      ? item.details.reason
      : JSON.stringify(item.details),
    actor: item.actor,
    kind: timelineKind(item),
    correlationId: item.correlation_id,
  }))
}

async function assetUrl(assetId?: string | null): Promise<string> {
  if (!assetId) return '/mock/blender/transistor-bent-lead.png'
  const cached = assetUrlCache.get(assetId)
  if (cached) return cached
  const request = apiRequestBlob(`/assets/${assetId}`).catch((error) => {
    assetUrlCache.delete(assetId)
    throw error
  })
  assetUrlCache.set(assetId, request)
  return request
}

function policyThreshold(snapshot: Record<string, unknown>, key: string, fallback: number): number {
  const defaults = snapshot.default
  if (defaults && typeof defaults === 'object') {
    const value = (defaults as Record<string, unknown>)[key]
    if (typeof value === 'number') return value
  }
  return fallback
}

async function normalizeInspection(raw: RawInspection, withTimeline = false): Promise<Inspection> {
  const original = raw.images.find((item) => item.kind === 'ORIGINAL') ?? raw.images[0]
  const heatmap = raw.images.find((item) => item.kind === 'HEATMAP')
  const [originalUrl, heatmapUrl, timeline] = await Promise.all([
    assetUrl(original?.id),
    heatmap ? assetUrl(heatmap.id) : Promise.resolve(undefined),
    withTimeline
      ? apiRequest<RawTimeline[]>(`/inspections/${raw.inspection_id}/timeline`)
      : Promise.resolve([]),
  ])
  const policy = raw.policy
  return {
    id: raw.inspection_id,
    status: raw.status,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    correlationId: raw.correlation_id,
    context: {
      tenantId: raw.tenant_id,
      productCode: raw.context.product_code,
      productRevision: raw.context.product_revision ?? '—',
      batchNo: raw.context.batch_no,
      station: raw.context.station_code,
      capturedAt: raw.context.captured_at,
      source: raw.context.source,
      metadata: raw.context.metadata ?? {},
    },
    image: {
      filename: `${raw.inspection_id}.${original?.mime_type === 'image/jpeg' ? 'jpg' : 'png'}`,
      originalUrl,
      heatmapUrl,
      mimeType: original?.mime_type ?? 'image/png',
      width: original?.width ?? 1,
      height: original?.height ?? 1,
      sha256: original?.sha256 ?? '',
    },
    inference: raw.model ? {
      score: raw.model.score,
      latencyMs: raw.model.latency_ms,
      modelId: raw.model.model_id,
      modelVersion: raw.model.model_version,
      featureBankVersion: raw.model.feature_bank_version,
      device: raw.model.runtime_device,
      semanticDefectConfirmed: false,
    } : undefined,
    policy: policy ? {
      version: policy.version,
      reviewThreshold: policyThreshold(policy.snapshot, 'review_threshold', 0.4),
      holdThreshold: policyThreshold(policy.snapshot, 'hold_threshold', 0.8),
      decision: policy.decision as NonNullable<Inspection['policy']>['decision'],
      reason: policy.reason,
    } : undefined,
    reviewTaskId: raw.review_task_id ?? undefined,
    incidentId: raw.incident_id ?? undefined,
    failure: raw.failure_reason ? {
      code: 'INFERENCE_FAILED',
      message: raw.failure_reason,
      nextStep: '请由人工复核证据，确认模型与部署包状态。',
    } : undefined,
    qualityFlags: raw.quality_flags ?? [],
    timeline: normalizeTimeline(timeline),
  }
}

function normalizeExternalAction(raw: RawExternalAction): ExternalAction {
  const status: ExternalAction['status'] = raw.status === 'SUCCEEDED'
    ? 'COMPLETED'
    : raw.status === 'MANUAL_REVIEW' ? 'FAILED' : raw.status as ExternalAction['status']
  return {
    id: raw.id,
    system: raw.connector === 'MES'
      ? 'Mock MES'
      : raw.connector === 'QMS' ? 'Mock QMS' : 'Simulated DXQ',
    action: raw.operation,
    status,
    attempts: raw.attempts,
    externalRef: raw.external_reference ?? undefined,
    idempotencyKey: raw.idempotency_key,
    updatedAt: raw.updated_at,
    message: raw.last_error ?? (status === 'COMPLETED' ? '外部操作已幂等完成。' : '等待执行。'),
  }
}

export const visionQcApi = {
  async getSystemHealth(): Promise<SystemHealth> {
    return apiRequest<SystemHealth>('/health')
  },

  async getTenantContext(): Promise<TenantContext> {
    return normalizeTenantContext(await apiRequest<RawTenantContext | TenantContext>('/tenant-context'))
  },

  async listGatewayStatuses(): Promise<GatewayStatus[]> {
    const rows = await apiRequest<RawGatewayStatus[]>('/gateways/status')
    return rows.map((row) => ({
      tenantId: row.tenant_id,
      gatewayId: row.gateway_id,
      gatewayVersion: row.gateway_version,
      stationCode: row.station_code,
      status: row.status,
      reportedStatus: row.reported_status,
      queueDepth: row.queue_depth,
      lastError: row.last_error ?? undefined,
      lastHeartbeatAt: row.last_heartbeat_at,
      lastUploadSucceededAt: row.last_upload_succeeded_at ?? undefined,
      lastUploadFailedAt: row.last_upload_failed_at ?? undefined,
      uploadSuccessCount: row.upload_success_count,
      uploadFailureCount: row.upload_failure_count,
      deploymentPackKey: row.deployment_pack_key ?? undefined,
      deploymentPackVersion: row.deployment_pack_version ?? undefined,
      metrics: row.metrics ?? {},
      uploadEnabled: row.upload_enabled,
      dataConsent: row.data_consent,
      dataPurpose: row.data_purpose,
      retentionDays: row.retention_days,
      deleteAfterUpload: row.delete_after_upload,
      localProcessingDefault: row.local_processing_default,
      cameraEnabled: row.camera_enabled,
      cameraIndex: row.camera_index,
    }))
  },

  async getOperationsSummary(): Promise<OperationsSummary> {
    const raw = await apiRequest<RawOperationsSummary>('/operations/summary')
    return {
      tenantId: raw.tenant_id,
      generatedAt: raw.generated_at,
      windowHours: raw.window_hours,
      inspections24h: raw.inspections_24h,
      routeCounts: raw.route_counts,
      reviewBacklog: raw.review_backlog,
      reviewHighRisk: raw.review_high_risk,
      incidentCounts: raw.incident_counts,
      gatewaysTotal: raw.gateways_total,
      gatewaysOnline: raw.gateways_online,
      gatewayOnlineRate: raw.gateway_online_rate ?? undefined,
      gatewayQueueDepth: raw.gateway_queue_depth,
      uploadSuccessCount: raw.upload_success_count,
      uploadFailureCount: raw.upload_failure_count,
    }
  },

  async listIncidents(): Promise<IncidentSummary[]> {
    const rows = await apiRequest<RawIncidentSummary[]>('/incidents')
    return rows.map((row) => ({
      id: row.id,
      inspectionId: row.inspection_id,
      status: row.status,
      severity: row.severity,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
      owner: row.owner ?? undefined,
      disposition: row.disposition,
      batchNo: row.batch_no,
      productCode: row.product_code,
      station: row.station_code,
    }))
  },

  async getModelOpsStatus(): Promise<ModelOpsStatus> {
    const raw = await apiRequest<RawModelOpsStatus>('/modelops/status')
    return {
      tenantId: raw.tenant_id,
      packKey: raw.pack_key,
      deploymentVersion: raw.deployment_version,
      deploymentStatus: raw.deployment_status,
      productCode: raw.product_code,
      modelId: raw.model_id,
      modelVersion: raw.model_version,
      featureBankVersion: raw.feature_bank_version,
      packageVerified: raw.package_verified,
      modelReleaseStatus: raw.model_release_status,
      syntheticSmoke: raw.synthetic_smoke,
      smokeChecksPassed: raw.smoke_checks_passed,
      smokeChecksTotal: raw.smoke_checks_total,
      testSamples: raw.test_samples,
      mvtecMetricsAvailable: raw.mvtec_metrics_available,
      calibrationConstraintsSatisfied: raw.calibration_constraints_satisfied,
      reportGeneratedAt: raw.report_generated_at,
      evidenceSource: raw.evidence_source,
      limitations: raw.limitations,
      releaseRecommendation: raw.release_recommendation,
      qualificationStatus: raw.qualification_status ?? 'INSUFFICIENT_EVIDENCE',
      modelPackageSha256: raw.model_package_sha256 ?? undefined,
      evidencePackageSha256: raw.evidence_package_sha256 ?? undefined,
      gateResults: raw.gate_results ?? {},
      activationAllowed: raw.activation_allowed ?? false,
      datasetSourceType: raw.dataset_source_type ?? 'DEMO_SYNTHETIC',
      datasetSourceStatus: raw.dataset_source_status ?? undefined,
      datasetRegistrationId: raw.dataset_registration_id ?? undefined,
      datasetFingerprint: raw.dataset_fingerprint ?? undefined,
      reportStatus: raw.report_status ?? raw.qualification_status ?? 'DEMO_ONLY',
      customerDataGate: raw.customer_data_gate ?? 'BLOCKED_NO_CUSTOMER_DATA',
      riskLabels: raw.risk_labels ?? [],
    }
  },

  async switchTenant(tenantId: string): Promise<TenantContext> {
    const response = await apiRequest<{ access_token: string }>('/auth/switch-tenant', {
      method: 'POST',
      body: { tenant_id: tenantId },
    })
    if (response.access_token) replaceAccessToken(response.access_token)
    return this.getTenantContext()
  },

  async createInspection(input: InspectionUpload): Promise<CreateInspectionResponse> {
    const form = new FormData()
    form.set('image', input.file)
    const fieldMapping = input.fieldMapping ?? {
      productCode: 'product_code',
      productRevision: 'product_revision',
      batchNo: 'batch_no',
      stationCode: 'station_code',
      capturedAt: 'captured_at',
      source: 'source',
    }
    form.set(fieldMapping.productCode, input.productCode)
    form.set(fieldMapping.productRevision, input.productRevision)
    form.set(fieldMapping.batchNo, input.batchNo)
    form.set(fieldMapping.stationCode, input.station)
    form.set(fieldMapping.capturedAt, input.capturedAt)
  form.set(fieldMapping.source, input.source ?? 'Web manual upload')
  if (input.metadata) form.set('context_metadata_json', JSON.stringify(input.metadata))

    const raw = await apiRequest<CreateInspectionResponse | RawInspection>('/inspections', {
      method: 'POST',
      body: form,
      idempotencyKey: input.idempotencyKey,
    })
    if ('inspectionId' in raw) return raw
    return {
      inspectionId: raw.inspection_id,
      status: raw.status,
      deduplicated: raw.idempotent_replay,
      correlationId: raw.correlation_id,
    }
  },

  async getInspection(id: string): Promise<Inspection> {
    const raw = await apiRequest<Inspection | RawInspection>(`/inspections/${id}`)
    return isUiInspection(raw) ? raw : normalizeInspection(raw, true)
  },

  async listRecentInspections(): Promise<Inspection[]> {
    const rows = await apiRequest<Array<Inspection | RawInspection>>('/inspections')
    return Promise.all(rows.map((row) => isUiInspection(row) ? row : normalizeInspection(row)))
  },

  async listReviews(): Promise<ReviewTask[]> {
    const rows = await apiRequest<Array<ReviewTask | RawReviewTask>>('/reviews')
    return Promise.all(rows.map(async (row) => {
      if ('inspectionId' in row) return row
      return {
        id: row.id,
        version: row.version,
        inspectionId: row.inspection_id,
        status: row.status,
        priority: row.priority,
        assignee: row.assignee ?? undefined,
        slaAt: row.sla_at ?? new Date(Date.now() + 30 * 60_000).toISOString(),
        score: row.score ?? undefined,
        route: row.route,
        batchNo: row.batch_no,
        productCode: row.product_code,
        station: row.station_code,
        thumbnailUrl: await assetUrl(row.thumbnail_asset_id),
        held: row.held,
      }
    }))
  },

  async submitReviewDecision(taskId: string, submission: ReviewSubmission): Promise<ReviewReceipt> {
    if (USE_MOCKS) {
      return apiRequest<ReviewReceipt>(`/reviews/${taskId}/decisions`, {
        method: 'POST',
        body: submission as unknown as Record<string, unknown>,
        idempotencyKey: `review-${taskId}-v${submission.expectedVersion}`,
      })
    }
    const raw = await apiRequest<{
      review_task_id: string
      decision_id: string
      inspection_status: InspectionStatus
      incident_id?: string | null
      submitted_at: string
      actor: string
      correlation_id: string
    }>(`/reviews/${taskId}/decisions`, {
      method: 'POST',
      body: {
        expected_version: submission.expectedVersion,
        decision: submission.decision === 'PASS'
          ? 'GOOD'
          : submission.decision === 'UNABLE_TO_DECIDE'
            ? 'UNABLE_TO_DETERMINE'
            : submission.decision,
        reason: submission.reasonCode,
        notes: submission.note,
        confirmed: submission.impactConfirmed,
        model_feedback: submission.modelFeedback === 'FALSE_POSITIVE'
          ? 'FALSE_POSITIVE'
          : submission.modelFeedback === 'POSSIBLE_MISS'
            ? 'SUSPECTED_FALSE_NEGATIVE'
            : undefined,
      },
      idempotencyKey: `review-${taskId}-v${submission.expectedVersion}`,
    })
    return {
      reviewTaskId: raw.review_task_id,
      decisionId: raw.decision_id,
      inspectionStatus: raw.inspection_status,
      incidentId: raw.incident_id ?? undefined,
      submittedAt: raw.submitted_at,
      actor: raw.actor,
      correlationId: raw.correlation_id,
    }
  },

  async getIncident(id: string): Promise<QualityIncident> {
    const raw = await apiRequest<QualityIncident | RawIncident>(`/incidents/${id}`)
    if ('inspectionId' in raw) return raw
    const status = raw.status === 'ACTION_COMPLETED' || raw.status === 'ACTION_FAILED'
      ? 'VERIFYING'
      : raw.status as QualityIncident['status']
    return {
      id: raw.id,
      inspectionId: raw.inspection_id,
      status,
      severity: raw.severity,
      createdAt: raw.created_at,
      updatedAt: raw.updated_at,
      owner: raw.owner ?? '待分配',
      disposition: raw.disposition,
      outcome: raw.outcome ?? undefined,
      verificationRecord: raw.verification_record ?? undefined,
      batchNo: raw.batch_no,
      productCode: raw.product_code,
      station: raw.station_code,
      evidence: {
        score: raw.evidence.score,
        modelVersion: raw.evidence.model_version,
        policyVersion: raw.evidence.policy_version,
        decisionActor: raw.evidence.decision_actor,
        decisionReason: raw.evidence.decision_reason,
      },
      externalActions: raw.external_actions.map(normalizeExternalAction),
      timeline: normalizeTimeline(raw.timeline),
      correlationId: raw.correlation_id,
    }
  },
}
