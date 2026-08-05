import type { ApiErrorPayload } from '../types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'
const USE_MOCKS = import.meta.env.VITE_USE_MOCKS !== 'false'
let demoTokenPromise: Promise<string> | undefined
let activeAccessToken: string | undefined

export function replaceAccessToken(token: string): void {
  activeAccessToken = token
  demoTokenPromise = Promise.resolve(token)
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail?: string
  readonly nextStep?: string
  readonly correlationId?: string

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message)
    this.name = 'ApiError'
    this.status = status
    this.code = payload.code
    this.detail = payload.detail
    this.nextStep = payload.nextStep
    this.correlationId = payload.correlationId
  }
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: BodyInit | Record<string, unknown>
  idempotencyKey?: string
}

async function accessToken(): Promise<string | undefined> {
  if (activeAccessToken) return activeAccessToken
  const configured = import.meta.env.VITE_API_TOKEN as string | undefined
  if (configured) return configured
  if (USE_MOCKS) return undefined
  demoTokenPromise ??= fetch(`${API_BASE_URL}/auth/demo-token`, {
    headers: { Accept: 'application/json' },
  })
    .then(async (response) => {
      if (!response.ok) throw new Error('未配置生产访问令牌，且演示令牌不可用。')
      const payload = (await response.json()) as { access_token: string }
      return payload.access_token
    })
    .catch((error) => {
      demoTokenPromise = undefined
      throw error
    })
  return demoTokenPromise
}

async function requestHeaders(options: RequestOptions): Promise<Headers> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  const token = await accessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey)
  return headers
}

async function throwApiError(response: Response): Promise<never> {
  let payload: ApiErrorPayload
  try {
    const raw = (await response.json()) as Record<string, unknown>
    payload = {
      code: String(raw.code ?? 'UNEXPECTED_RESPONSE'),
      message: String(raw.message ?? raw.detail ?? `请求失败（HTTP ${response.status}）`),
      detail: typeof raw.detail === 'string' ? raw.detail : undefined,
      nextStep: typeof raw.nextStep === 'string' ? raw.nextStep : undefined,
      correlationId: typeof raw.correlation_id === 'string'
        ? raw.correlation_id
        : typeof raw.correlationId === 'string' ? raw.correlationId : undefined,
    }
  } catch {
    payload = {
      code: 'UNEXPECTED_RESPONSE',
      message: `请求失败（HTTP ${response.status}）`,
      nextStep: '请稍后重试；若问题持续，请联系系统管理员。',
    }
  }
  throw new ApiError(response.status, payload)
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && Object.getPrototypeOf(value) === Object.prototype
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = await requestHeaders(options)

  const body = isPlainObject(options.body) ? JSON.stringify(options.body) : options.body
  if (isPlainObject(options.body)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    body,
  })

  if (!response.ok) {
    return throwApiError(response)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function apiRequestBlob(path: string): Promise<string> {
  const headers = await requestHeaders({})
  const response = await fetch(`${API_BASE_URL}${path}`, { headers })
  if (!response.ok) return throwApiError(response)
  const blob = await response.blob()
  return URL.createObjectURL(blob)
}
