import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AppRoutes } from './App'
import { DEFAULT_TENANT_CONFIG } from './config/tenant'
import { mockTenantConfigAdapter, tenantConfigIntegrationAssumptions } from './api/tenantConfig'

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<AppRoutes />)
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
})

afterEach(() => undefined)

describe('white-label runtime experience', () => {
  it('starts with neutral branding and switches the full shell to English', async () => {
    const user = userEvent.setup()
    renderAt('/')

    expect(screen.getAllByText('VisionQC Platform').length).toBeGreaterThan(0)
    expect(document.querySelector('.tenant-logo')).toBeNull()
    expect(await screen.findByRole('heading', { name: '质量工作台' })).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toHaveTextContent('总览')

    await user.click(screen.getByRole('button', { name: 'English' }))

    expect(await screen.findByRole('heading', { name: 'Quality Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('navigation')).toHaveTextContent('Overview')
    expect(screen.getByRole('navigation')).not.toHaveTextContent('总览')
    expect(document.documentElement.lang).toBe('en')
    expect(document.title).toContain('VisionQC Platform')

    await user.click(screen.getByRole('button', { name: '中文' }))
    expect(await screen.findByRole('heading', { name: '质量工作台' })).toBeInTheDocument()
  })

  it('applies an industry glossary and automotive concept boundary at runtime', async () => {
    const user = userEvent.setup()
    renderAt('/setup')

    expect(screen.getAllByText('电子装配').length).toBeGreaterThan(0)
    expect(screen.getAllByText('包装').length).toBeGreaterThan(0)
    expect(screen.getAllByText('汽车涂装').length).toBeGreaterThan(0)

    const automotiveCard = screen.getByText('汽车涂装').closest('button')
    expect(automotiveCard).not.toBeNull()
    await user.click(automotiveCard!)

    expect(screen.getByText('Independent portfolio concept; not commissioned or endorsed by Dürr.')).toBeInTheDocument()
    expect(screen.getAllByText(/汽车涂装/).length).toBeGreaterThan(0)
    expect(document.querySelector('.app-shell')).toHaveStyle('--industry-wash: #f4eee8')

    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(await screen.findByRole('heading', { name: '填企业与工厂信息' })).toBeInTheDocument()
    const companyInput = screen.getByDisplayValue('VisionQC Platform')
    await user.clear(companyInput)
    await user.type(companyInput, 'Northstar QA')
    expect(screen.getAllByText('Northstar QA').length).toBeGreaterThan(0)
    expect(screen.queryByRole('img', { name: /logo/i })).toBeNull()
  })

  it('completes the six-step setup in mock mode with conservative privacy defaults', async () => {
    const user = userEvent.setup()
    renderAt('/start')

    for (let step = 0; step < 3; step += 1) {
      await user.click(screen.getByRole('button', { name: '下一步' }))
    }

    expect(await screen.findByRole('heading', { name: '选择处理与保留策略' })).toBeInTheDocument()
    const privacyChecks = screen.getAllByRole('checkbox')
    expect(privacyChecks.every((checkbox) => !(checkbox as HTMLInputElement).checked)).toBe(true)
    expect(screen.getByDisplayValue('30')).toBeInTheDocument()
    expect(screen.getByText(/隐私默认值偏保守/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(await screen.findByRole('heading', { name: '选择连接器并测试' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '模拟连接测试' }))
    expect(await screen.findByText('测试通过（模拟）')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '下一步' }))
    expect(await screen.findByRole('heading', { name: '风险策略预览' })).toBeInTheDocument()
    expect(screen.getByText('LOCKED')).toBeInTheDocument()
    expect(screen.getAllByText('始终开启，不能关闭').length).toBeGreaterThan(0)

    await user.click(screen.getByRole('button', { name: '生成并进入工作台' }))
    expect(await screen.findByRole('heading', { name: '质量工作台' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '你的工作台已准备好' })).toBeInTheDocument()
  })

  it('aligns mock product and station examples with the selected industry after generation', async () => {
    const user = userEvent.setup()
    renderAt('/start')

    await user.click(screen.getByRole('button', { name: /汽车涂装/ }))
    for (let step = 0; step < 5; step += 1) {
      await user.click(screen.getByRole('button', { name: '下一步' }))
    }
    await user.click(screen.getByRole('button', { name: '生成并进入工作台' }))
    await user.click((await screen.findAllByRole('link', { name: '上传图片' }))[0])

    expect(await screen.findByRole('combobox', { name: /车身（Body）编号/ })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'PAINTED-BODY-DEMO · 车身漆面' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'PAINT-QC-01 · 漆面终检' })).toBeInTheDocument()
  })

  it('keeps the future tenant API seam typed and simulated', async () => {
    expect(tenantConfigIntegrationAssumptions).toMatchObject({ mode: 'local-mock', backendAvailable: false, connectorWritesEnabled: false })
    const fixture = await mockTenantConfigAdapter.get()
    expect(fixture).toEqual(DEFAULT_TENANT_CONFIG)
    const result = await mockTenantConfigAdapter.testConnector(fixture.connectors)
    expect(result).toEqual({ status: 'PASSED', correlationId: 'corr-MOCK-CONNECTOR-TEST', simulated: true })
  })

  it('supports long Chinese setup copy without losing the responsive source controls', async () => {
    const user = userEvent.setup()
    renderAt('/start')
    await user.click(screen.getByRole('button', { name: /USB 相机/ }))
    expect(screen.getByText(/默认本地处理，不上传客户原图/)).toBeInTheDocument()
    expect(screen.getByText(/未勾选同意时不会从网页上传客户原图/)).toBeInTheDocument()
    fireEvent.resize(window)
    await waitFor(() => expect(screen.getByRole('button', { name: '下一步' })).toBeEnabled())
  })
})
