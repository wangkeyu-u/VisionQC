export type InspectionStatus =
  | 'RECEIVED'
  | 'VALIDATED'
  | 'INFERENCING'
  | 'SCORED'
  | 'AUTO_RELEASED'
  | 'REVIEW_REQUIRED'
  | 'BATCH_HELD'
  | 'INFERENCE_FAILED'
  | 'RELEASE_APPROVED'
  | 'NONCONFORMANCE_CONFIRMED'
  | 'ACTION_PENDING'
  | 'ACTION_EXECUTING'
  | 'ACTION_COMPLETED'
  | 'VERIFYING'
  | 'ESCALATED'
  | 'CLOSED'

export type ReviewDecision =
  | 'PASS'
  | 'REWORK'
  | 'SCRAP'
  | 'INVESTIGATE'
  | 'UNABLE_TO_DECIDE'

export type TimelineKind = 'model' | 'policy' | 'human' | 'connector' | 'system'

export interface TimelineEvent {
  id: string
  occurredAt: string
  title: string
  detail: string
  actor: string
  kind: TimelineKind
  correlationId: string
}

export interface InspectionContext {
  tenantId: string
  productCode: string
  productRevision: string
  batchNo: string
  station: string
  capturedAt: string
  source: string
}

export interface ImageAsset {
  filename: string
  originalUrl: string
  heatmapUrl?: string
  mimeType: string
  width: number
  height: number
  sha256: string
}

export interface InferenceResult {
  score: number
  latencyMs: number
  modelId: string
  modelVersion: string
  featureBankVersion: string
  device: string
  semanticDefectConfirmed: false
}

export interface PolicyDecision {
  version: string
  reviewThreshold: number
  holdThreshold: number
  decision: 'AUTO_RELEASE' | 'MANUAL_REVIEW' | 'BATCH_HOLD_AND_REVIEW' | 'SAFE_REVIEW'
  reason: string
}

export interface Inspection {
  id: string
  status: InspectionStatus
  createdAt: string
  updatedAt: string
  correlationId: string
  context: InspectionContext
  image: ImageAsset
  inference?: InferenceResult
  policy?: PolicyDecision
  reviewTaskId?: string
  incidentId?: string
  failure?: {
    code: string
    message: string
    nextStep: string
  }
  timeline: TimelineEvent[]
}

export interface ReviewTask {
  id: string
  version: number
  inspectionId: string
  status: 'OPEN' | 'CLAIMED' | 'COMPLETED' | 'ESCALATED'
  priority: 'STANDARD' | 'HIGH' | 'CRITICAL'
  assignee?: string
  slaAt: string
  score?: number
  route: 'GREY_ZONE' | 'HIGH_SCORE_HOLD' | 'SAFE_DEGRADE'
  batchNo: string
  productCode: string
  station: string
  thumbnailUrl: string
  held: boolean
}

export interface ReviewSubmission {
  decision: ReviewDecision
  reasonCode: string
  note: string
  expectedVersion: number
  modelFeedback?: 'FALSE_POSITIVE' | 'POSSIBLE_MISS' | 'NONE'
  impactConfirmed: boolean
}

export interface ReviewReceipt {
  reviewTaskId: string
  decisionId: string
  inspectionStatus: InspectionStatus
  incidentId?: string
  submittedAt: string
  actor: string
  correlationId: string
}

export interface ExternalAction {
  id: string
  system: 'Mock MES' | 'Mock QMS'
  action: string
  status: 'PENDING' | 'EXECUTING' | 'COMPLETED' | 'FAILED'
  attempts: number
  externalRef?: string
  idempotencyKey: string
  updatedAt: string
  message: string
}

export interface QualityIncident {
  id: string
  inspectionId: string
  status: 'OPEN' | 'ACTION_PENDING' | 'ACTION_EXECUTING' | 'VERIFYING' | 'CLOSED' | 'ESCALATED'
  severity: 'MAJOR' | 'CRITICAL'
  createdAt: string
  updatedAt: string
  owner: string
  disposition: 'REWORK' | 'SCRAP' | 'INVESTIGATE'
  outcome?: string
  verificationRecord?: string
  batchNo: string
  productCode: string
  station: string
  evidence: {
    score: number
    modelVersion: string
    policyVersion: string
    decisionActor: string
    decisionReason: string
  }
  externalActions: ExternalAction[]
  timeline: TimelineEvent[]
  correlationId: string
}

export interface CreateInspectionResponse {
  inspectionId: string
  status: InspectionStatus
  deduplicated: boolean
  correlationId: string
}

export interface ApiErrorPayload {
  code: string
  message: string
  detail?: string
  nextStep?: string
  correlationId?: string
}

export interface DeploymentProduct {
  code: string
  displayName: string
  revision: string
  aliases: string[]
}

export interface DeploymentStation {
  code: string
  displayName: string
  description: string
  cameraProfile: string
}

export interface DeploymentFieldMapping {
  productCode: string
  productRevision: string
  batchNo: string
  stationCode: string
  capturedAt: string
  source: string
}

export interface DeploymentModel {
  id: string
  version: string
  featureBankVersion: string
  adapter: string
  runtime: string
  device: string
  packageUri: string
  packageSha256?: string | null
  scoreSemantics: string
  limitations: string[]
}

export interface DeploymentConnector {
  displayName: string
  driver: string
  contractVersion: string
  endpoint: string
  payloadMapping: Record<string, string>
  fixedFields: Record<string, unknown>
  operations: string[]
}

export interface DeploymentPolicy {
  version: string
  default: { reviewThreshold: number; holdThreshold: number }
  overrides: Array<{
    productCode?: string | null
    stationCode?: string | null
    reviewThreshold: number
    holdThreshold: number
  }>
}

export interface DeploymentPack {
  id: string
  tenantId: string
  version: string
  status: string
  packKey: string
  displayName: string
  inputMode: 'api_upload' | 'folder_watch'
  products: DeploymentProduct[]
  stations: DeploymentStation[]
  fieldMapping: DeploymentFieldMapping
  fieldLabels: Record<string, string>
  model: DeploymentModel
  policy: DeploymentPolicy
  connectors: {
    mes: DeploymentConnector
    qms: DeploymentConnector
  }
  metadata: Record<string, unknown>
}

export interface TenantSummary {
  id: string
  name: string
  status: string
}

export interface TenantContext {
  tenant: TenantSummary
  currentDeployment?: DeploymentPack
  availableTenants: TenantSummary[]
}

export interface GatewayStatus {
  tenantId: string
  gatewayId: string
  gatewayVersion: string
  stationCode: string
  status: 'ONLINE' | 'DEGRADED' | 'STALE' | 'OFFLINE' | 'STARTING' | 'STOPPING'
  reportedStatus: string
  queueDepth: number
  lastError?: string
  lastHeartbeatAt: string
  lastUploadSucceededAt?: string
  lastUploadFailedAt?: string
  uploadSuccessCount: number
  uploadFailureCount: number
  deploymentPackKey?: string
  deploymentPackVersion?: string
  metrics: Record<string, unknown>
}

export interface OperationsSummary {
  tenantId: string
  generatedAt: string
  windowHours: number
  inspections24h: number
  routeCounts: Record<string, number>
  reviewBacklog: number
  reviewHighRisk: number
  incidentCounts: Record<string, number>
  gatewaysTotal: number
  gatewaysOnline: number
  gatewayOnlineRate?: number
  gatewayQueueDepth: number
  uploadSuccessCount: number
  uploadFailureCount: number
}

export interface IncidentSummary {
  id: string
  inspectionId: string
  status: string
  severity: 'MAJOR' | 'CRITICAL' | string
  createdAt: string
  updatedAt: string
  owner?: string
  disposition: string
  batchNo: string
  productCode: string
  station: string
}

export interface ModelOpsStatus {
  tenantId: string
  packKey: string
  deploymentVersion: string
  deploymentStatus: string
  productCode: string
  modelId: string
  modelVersion: string
  featureBankVersion: string
  packageVerified: boolean
  modelReleaseStatus: 'DRAFT' | 'EVALUATED' | 'APPROVED' | 'ACTIVE' | 'RETIRED' | 'INSUFFICIENT_EVIDENCE' | 'REJECTED'
  syntheticSmoke: boolean
  smokeChecksPassed: number
  smokeChecksTotal: number
  testSamples: number
  mvtecMetricsAvailable: boolean
  calibrationConstraintsSatisfied: boolean
  reportGeneratedAt: string
  evidenceSource: string
  limitations: string[]
  releaseRecommendation: string[]
  qualificationStatus: string
  modelPackageSha256?: string
  evidencePackageSha256?: string
  gateResults: Record<string, unknown>
  activationAllowed: boolean
  datasetSourceType: 'DEMO_SYNTHETIC' | 'OFFICIAL_BENCHMARK' | 'CUSTOMER_PILOT'
  datasetSourceStatus?: 'DRAFT' | 'VALIDATED' | 'REVOKED'
  datasetRegistrationId?: string
  datasetFingerprint?: string
  reportStatus: string
  customerDataGate: string
  riskLabels: string[]
}
