import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { AppRoutes } from './App'
import { server } from './mocks/server'

function renderAt(path: string) {
  window.history.pushState({}, '', path)
  return render(<AppRoutes />)
}

describe('VisionQC quality workstation', () => {
  it('keeps the model boundary visible on the operations overview', async () => {
    renderAt('/')

    expect(screen.getByText(/异常不等于已确认缺陷/)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '今天的质量控制面' })).toBeInTheDocument()
    expect(screen.getByText(/检测吞吐/)).toBeInTheDocument()
    expect((await screen.findAllByText('B-240804-17')).length).toBeGreaterThan(0)
  })

  it('creates an inspection from the demo fixture and opens its persisted detail', async () => {
    const user = userEvent.setup()
    server.use(http.post('/api/v1/inspections', async () => HttpResponse.json({
      inspectionId: 'insp-240804-0087',
      status: 'RECEIVED',
      deduplicated: false,
      correlationId: 'corr-UPLOAD-TEST',
    }, { status: 201 })))
    renderAt('/upload')

    await user.click(screen.getByRole('button', { name: /载入演示样本/ }))
    expect(screen.getByAltText('待上传图像预览')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /创建检测任务/ }))

    expect(await screen.findByRole('heading', { name: '检测证据详情' })).toBeInTheDocument()
    expect(screen.getByText('仅暂扣，等待人工结论')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/inspections/insp-240804-0087')
  })

  it('shows versioned evidence and allows heatmap opacity control', async () => {
    const user = userEvent.setup()
    renderAt('/inspections/insp-240804-0087')

    expect(await screen.findByRole('heading', { name: '检测证据详情' })).toBeInTheDocument()
    expect(screen.getByText('异常响应不是缺陷确认')).toBeInTheDocument()
    expect(screen.getAllByText('patchcore-transistor@1.0.0').length).toBeGreaterThan(0)
    expect(screen.getByText('仅暂扣，等待人工结论')).toBeInTheDocument()

    const opacity = screen.getByRole('slider', { name: '热力图透明度' })
    fireEvent.change(opacity, { target: { value: '25' } })
    expect(screen.getByText('25%')).toBeInTheDocument()
  })

  it('requires a second confirmation for an investigation decision', async () => {
    const user = userEvent.setup()
    renderAt('/reviews/rev-240804-031')

    expect(await screen.findByRole('heading', { name: '质量复核工作台' })).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /调查/ }))
    await user.type(screen.getByPlaceholderText(/描述你在原图中观察到的事实/), '引脚根部存在可见污染，需要进一步调查来源。')
    await user.click(screen.getByRole('button', { name: /提交“调查”/ }))

    expect(screen.getByRole('dialog', { name: /确认提交“调查”处置/ })).toBeInTheDocument()
    expect(screen.getByText(/保持批次暂扣并创建调查质量事件/)).toBeInTheDocument()
    const confirmButton = screen.getByRole('button', { name: /确认并提交/ })
    expect(confirmButton).toBeDisabled()
    await user.click(screen.getByRole('checkbox', { name: /我已核对影响对象与现场证据/ }))
    await user.click(confirmButton)

    expect(await screen.findByRole('heading', { name: '复核决定已具名提交' })).toBeInTheDocument()
    expect(screen.getByText('已创建唯一质量事件')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /查看质量事件/ })).toHaveAttribute('href', '/incidents/qinc-240804-017')
  })

  it('reconstructs the incident connector and audit chain', async () => {
    renderAt('/incidents/qinc-240804-017')

    expect(await screen.findByRole('heading', { name: '质量事件 qinc-240804-017' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '外部业务操作' })).toBeInTheDocument()
    expect(screen.getByText(/未发现重复副作用/)).toBeInTheDocument()
    expect(screen.getByText('QMS-NCR-2026-1042')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/QMS 工单创建完成/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /条件未满足，不能关闭/ })).toBeDisabled()
  })

  it('switches the signed deployment context and surfaces its runtime contract', async () => {
    const user = userEvent.setup()
    renderAt('/modelops')

    const selector = await screen.findByRole('combobox', { name: '切换客户部署' })
    expect(screen.getByText('patchcore-transistor')).toBeInTheDocument()

    await user.selectOptions(selector, 'factory-b')

    await waitFor(() => expect(screen.getByRole('heading', { name: '今天的质量控制面' })).toBeInTheDocument())

    await user.click(screen.getByRole('link', { name: 'ModelOps' }))
    expect(await screen.findByText('patchcore-bottle')).toBeInTheDocument()
    expect(screen.getAllByText('factory_b/bottle').length).toBeGreaterThan(0)

    await user.click(screen.getAllByRole('link', { name: /手动上传/ })[0])
    expect((await screen.findAllByText('Factory B')).length).toBeGreaterThan(0)
    expect(screen.getByText('SKU')).toBeInTheDocument()
  })

  it('shows tenant-scoped edge gateway backlog and heartbeat status', async () => {
    renderAt('/operations')

    expect(await screen.findByRole('heading', { name: '工位 / Gateway 运营监测' })).toBeInTheDocument()
    expect(screen.getByText('factory-a-gw-st07 · v0.1.0')).toBeInTheDocument()
    expect(screen.getByText('本地待补传')).toBeInTheDocument()
    expect(screen.getByText('心跳与后端连通正常')).toBeInTheDocument()
  })
})
