import { delay, http, HttpResponse } from 'msw'
import type { Inspection, ReviewSubmission } from '../types'
import { incidentFixture, inspectionFixtures, recentInspectionIds, reviewFixtures, tenantContexts } from './fixtures'

const pollCounts = new Map<string, number>()
const uploads = new Map<string, Inspection>()
let mockTenant = 'factory-a'

export function resetMockTenant() {
  mockTenant = 'factory-a'
}

function notFound(resource: string) {
  return HttpResponse.json(
    {
      code: 'RESOURCE_NOT_FOUND',
      message: `未找到${resource}`,
      nextStep: '请返回列表确认 ID，或使用关联 ID 联系管理员。',
      correlationId: 'corr-NOT404',
    },
    { status: 404 },
  )
}

export const handlers = [
  http.get('/api/v1/health', async () => {
    return HttpResponse.json({ status: 'ok', checks: { storage: true, model: true } })
  }),

  http.get('/api/v1/tenant-context', async () => {
    return HttpResponse.json(structuredClone(tenantContexts[mockTenant]))
  }),

  http.get('/api/v1/gateways/status', async () => {
    const gateway = mockTenant === 'factory-a'
      ? { gatewayId: 'factory-a-gw-st07', station: 'ST-07 / 终检', pack: 'factory_a/transistor', version: '1.0.0', queue: 0, success: 128 }
      : mockTenant === 'factory-b'
        ? { gatewayId: 'factory-b-gw-cell12', station: 'CELL-12', pack: 'factory_b/bottle', version: '2.1.0', queue: 1, success: 64 }
        : { gatewayId: 'duerr-demo-gw-paint-qc', station: 'PAINT-QC-01', pack: 'duerr_demo/paint_quality', version: '0.1.0', queue: 0, success: 12 }
    return HttpResponse.json([
      {
        tenant_id: mockTenant,
        gateway_id: gateway.gatewayId,
        gateway_version: '0.1.0',
        station_code: gateway.station,
        status: 'ONLINE',
        reported_status: 'ONLINE',
        queue_depth: gateway.queue,
        last_error: null,
        last_heartbeat_at: '2026-08-04T10:42:18+08:00',
        last_upload_succeeded_at: '2026-08-04T10:41:55+08:00',
        last_upload_failed_at: null,
        upload_success_count: gateway.success,
        upload_failure_count: 1,
        deployment_pack_key: gateway.pack,
        deployment_pack_version: gateway.version,
        upload_enabled: false,
        data_consent: false,
        data_purpose: '本地涂装质量检测与人工复核',
        retention_days: 30,
        delete_after_upload: false,
        local_processing_default: true,
        camera_enabled: false,
        camera_index: 0,
        metrics: { queue_counts: { UPLOADED: gateway.success } },
      },
    ])
  }),

  http.get('/api/v1/operations/summary', async () => {
    const inspections = [
      ...(mockTenant === 'factory-a' ? recentInspectionIds.map((id) => inspectionFixtures[id]) : []),
      ...[...uploads.values()].filter((inspection) => inspection.context.tenantId === mockTenant),
    ]
    const reviews = mockTenant === 'factory-a' ? reviewFixtures : []
    const incidents = mockTenant === 'factory-a' ? [incidentFixture] : []
    const gateways = mockTenant === 'factory-a'
      ? { total: 1, online: 1, queue: 0, success: 128, failure: 1 }
      : mockTenant === 'factory-b'
        ? { total: 1, online: 1, queue: 1, success: 64, failure: 1 }
        : { total: 1, online: 1, queue: 0, success: 12, failure: 0 }
    const routeCounts = inspections.reduce<Record<string, number>>((counts, inspection) => {
      const route = inspection.policy?.decision ?? (inspection.failure ? 'SAFE_REVIEW' : 'PENDING')
      counts[route] = (counts[route] ?? 0) + 1
      return counts
    }, {})
    const incidentCounts = incidents.reduce<Record<string, number>>((counts, incident) => {
      counts[incident.status] = (counts[incident.status] ?? 0) + 1
      return counts
    }, {})
    return HttpResponse.json({
      tenant_id: mockTenant,
      generated_at: new Date().toISOString(),
      window_hours: 24,
      inspections_24h: inspections.length,
      route_counts: routeCounts,
      review_backlog: reviews.length,
      review_high_risk: reviews.filter((task) => task.held).length,
      incident_counts: incidentCounts,
      gateways_total: gateways.total,
      gateways_online: gateways.online,
      gateway_online_rate: gateways.online / gateways.total,
      gateway_queue_depth: gateways.queue,
      upload_success_count: gateways.success,
      upload_failure_count: gateways.failure,
    })
  }),

  http.post('/api/v1/auth/switch-tenant', async ({ request }) => {
    const body = (await request.json()) as { tenant_id?: string }
    if (!body.tenant_id || !tenantContexts[body.tenant_id]) {
      return HttpResponse.json({ code: 'TENANT_SWITCH_FORBIDDEN', message: '客户切换被拒绝。' }, { status: 403 })
    }
    mockTenant = body.tenant_id
    return HttpResponse.json({ access_token: `mock-token-${mockTenant}` })
  }),

  http.get('/api/v1/inspections', async () => {
    await delay(220)
    return HttpResponse.json(mockTenant === 'factory-a' ? recentInspectionIds.map((id) => inspectionFixtures[id]) : [])
  }),

  http.post('/api/v1/inspections', async ({ request }) => {
    await delay(450)
    const form = await request.formData()
    const image = form.get('image')
    const imageFile = typeof image === 'object' && image !== null && 'name' in image ? image as File : null
    const idempotencyKey = request.headers.get('Idempotency-Key')
    const deployment = tenantContexts[mockTenant].currentDeployment
    const mapping = deployment?.fieldMapping
    const read = (key: string | undefined) => key ? form.get(key) : null

    if (!imageFile || !read(mapping?.batchNo) || !read(mapping?.stationCode) || !read(mapping?.productCode)) {
      return HttpResponse.json(
        {
          code: 'INVALID_INSPECTION_INPUT',
          message: '图片与业务上下文不完整，未创建检测任务。',
          detail: 'image、batch_no、station 均为必填字段。',
          nextStep: '补齐标记字段后重新提交。',
          correlationId: 'corr-UPL400',
        },
        { status: 400 },
      )
    }

    const existing = [...uploads.values()].find((inspection) => inspection.correlationId === idempotencyKey)
    if (existing) {
      return HttpResponse.json({
        inspectionId: existing.id,
        status: existing.status,
        deduplicated: true,
        correlationId: existing.correlationId,
      })
    }

    const id = `insp-demo-${String(uploads.size + 1).padStart(3, '0')}`
    const createdAt = new Date().toISOString()
    const inspection: Inspection = {
      ...structuredClone(inspectionFixtures['insp-240804-0087']),
      id,
      status: 'RECEIVED',
      createdAt,
      updatedAt: createdAt,
      correlationId: idempotencyKey ?? `corr-${id}`,
      context: {
        ...inspectionFixtures['insp-240804-0087'].context,
        tenantId: mockTenant,
        productCode: String(read(mapping?.productCode)),
        productRevision: String(read(mapping?.productRevision)),
        batchNo: String(read(mapping?.batchNo)),
        station: String(read(mapping?.stationCode)),
        capturedAt: String(read(mapping?.capturedAt)),
      },
      image: {
        ...inspectionFixtures['insp-240804-0087'].image,
        filename: imageFile.name,
      },
      reviewTaskId: undefined,
      incidentId: undefined,
      timeline: inspectionFixtures['insp-240804-0087'].timeline.slice(0, 1),
    }
    uploads.set(id, inspection)
    pollCounts.set(id, 0)

    return HttpResponse.json(
      { inspectionId: id, status: 'RECEIVED', deduplicated: false, correlationId: inspection.correlationId },
      { status: 201 },
    )
  }),

  http.get('/api/v1/inspections/:id', async ({ params }) => {
    await delay(180)
    const id = String(params.id)
    const seeded = inspectionFixtures[id]
    if (seeded && seeded.context.tenantId === mockTenant) return HttpResponse.json(seeded)

    const uploaded = uploads.get(id)
    if (!uploaded) return notFound('检测任务')

    const nextCount = (pollCounts.get(id) ?? 0) + 1
    pollCounts.set(id, nextCount)
    const status = nextCount === 1 ? 'INFERENCING' : 'BATCH_HELD'
    return HttpResponse.json({
      ...uploaded,
      status,
      updatedAt: new Date().toISOString(),
      timeline:
        status === 'INFERENCING'
          ? uploaded.timeline
          : inspectionFixtures['insp-240804-0087'].timeline.slice(0, 3),
    })
  }),

  http.get('/api/v1/reviews', async () => {
    await delay(300)
    return HttpResponse.json(mockTenant === 'factory-a' ? reviewFixtures : [])
  }),

  http.get('/api/v1/incidents', async () => {
    await delay(180)
    return HttpResponse.json(mockTenant === 'factory-a' ? [{
      id: incidentFixture.id,
      inspection_id: incidentFixture.inspectionId,
      status: incidentFixture.status,
      severity: incidentFixture.severity,
      created_at: incidentFixture.createdAt,
      updated_at: incidentFixture.updatedAt,
      owner: incidentFixture.owner,
      disposition: incidentFixture.disposition,
      batch_no: incidentFixture.batchNo,
      product_code: incidentFixture.productCode,
      station_code: incidentFixture.station,
    }] : [])
  }),

  http.get('/api/v1/modelops/status', async () => {
    const deployment = tenantContexts[mockTenant].currentDeployment
    const product = deployment?.products[0]
    const model = deployment?.model
    return HttpResponse.json({
      tenant_id: mockTenant,
      pack_key: deployment?.packKey ?? 'unavailable',
      deployment_version: deployment?.version ?? '—',
      deployment_status: deployment?.status ?? 'UNKNOWN',
      product_code: product?.code ?? '—',
      model_id: model?.id ?? '—',
      model_version: model?.version ?? '—',
      feature_bank_version: model?.featureBankVersion ?? '—',
      package_verified: Boolean(model?.packageSha256),
      model_release_status: 'DRAFT',
      synthetic_smoke: true,
      smoke_checks_passed: 1,
      smoke_checks_total: 1,
      test_samples: 4,
      mvtec_metrics_available: false,
      calibration_constraints_satisfied: false,
      report_generated_at: '2026-08-04T14:38:00Z',
      evidence_source: 'reports/model-eval/smoke-evidence.json · ModelOps commit a25cce9',
      limitations: [
        ...(model?.limitations ?? []),
        '当前 smoke 仅使用每个产品 4 张 synthetic fixture；不代表 MVTec 或产线效果。',
        'OFFICIAL_BENCHMARK 尚未受控导入；阈值校准约束未满足。',
      ],
      release_recommendation: [
        '保持模型候选为 DRAFT / EVALUATED，不批准为生产 ACTIVE。',
        '如需 Benchmark Qualification，请受控导入官方 MVTec；客户数据必须另行提交完整 provenance。',
        '完成 shadow 对比、人工复核回流与回滚条件审查后再申请发布。',
      ],
      dataset_source_type: 'DEMO_SYNTHETIC',
      dataset_source_status: null,
      report_status: 'DEMO_ONLY',
      customer_data_gate: 'BLOCKED_NO_CUSTOMER_DATA',
      risk_labels: ['DEMO_ONLY', 'NO_EFFECT_CLAIM'],
    })
  }),

  http.post('/api/v1/reviews/:id/decisions', async ({ params, request }) => {
    await delay(500)
    const task = reviewFixtures.find((item) => item.id === params.id)
    if (!task) return notFound('复核任务')

    const body = (await request.json()) as ReviewSubmission
    if (body.expectedVersion !== task.version) {
      return HttpResponse.json(
        {
          code: 'REVIEW_VERSION_CONFLICT',
          message: '该任务已被其他质检员更新，本次决定未提交。',
          nextStep: '刷新任务并确认最新状态后再操作。',
          correlationId: 'corr-409REV',
        },
        { status: 409 },
      )
    }

    if (body.decision !== 'PASS' && body.decision !== 'UNABLE_TO_DECIDE' && (!body.reasonCode || !body.note)) {
      return HttpResponse.json(
        {
          code: 'REVIEW_REASON_REQUIRED',
          message: '该处置必须提供原因和备注。',
          nextStep: '选择标准原因并填写现场观察。',
          correlationId: 'corr-REV422',
        },
        { status: 422 },
      )
    }

    const createsIncident = ['REWORK', 'SCRAP', 'INVESTIGATE'].includes(body.decision)
    return HttpResponse.json(
      {
        reviewTaskId: task.id,
        decisionId: `rdec-${task.id.slice(-3)}-01`,
        inspectionStatus: createsIncident ? 'NONCONFORMANCE_CONFIRMED' : 'RELEASE_APPROVED',
        incidentId: createsIncident ? 'qinc-240804-017' : undefined,
        submittedAt: new Date().toISOString(),
        actor: '林知夏 / Inspector',
        correlationId: `corr-${task.id.slice(-6)}`,
      },
      { status: 201 },
    )
  }),

  http.get('/api/v1/incidents/:id', async ({ params }) => {
    await delay(260)
    if (params.id !== incidentFixture.id) return notFound('质量事件')
    return HttpResponse.json(incidentFixture)
  }),
]
