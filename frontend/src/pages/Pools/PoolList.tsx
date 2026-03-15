import React, { useEffect, useState, useRef } from 'react'
import {
  Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Space,
  Tag, Upload, message, Popconfirm, Select, Tooltip, AutoComplete,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, SyncOutlined, ReloadOutlined,
  PushpinOutlined, PushpinFilled, FileAddOutlined, HolderOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  listPools, createPool, updatePool, deletePool, reorderPools,
  listStocks, addStock, deleteStock, updateStock, importCSV, getAllStocks,
} from '../../api/pools'
import { searchStocks } from '../../api/stocks'
import { createPlan } from '../../api/plans'
import { syncPool, getTaskStatus } from '../../api/sync'
import type { Pool, WatchStock } from '../../types'

const TRIGGER_OPTIONS = ['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合']

const PoolList: React.FC = () => {
  const [pools, setPools] = useState<Pool[]>([])
  const [activePoolId, setActivePoolId] = useState<string>('')
  const [stocks, setStocks] = useState<WatchStock[]>([])
  const [loading, setLoading] = useState(false)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [editPoolModalOpen, setEditPoolModalOpen] = useState(false)
  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [planStock, setPlanStock] = useState<WatchStock | null>(null)
  const [createPlanModalOpen, setCreatePlanModalOpen] = useState(false)
  const [allStocks, setAllStocks] = useState<Array<{ ts_code: string; stock_name?: string }>>([])
  const [stockSearchOptions, setStockSearchOptions] = useState<Array<{ value: string; label: string }>>([])
  const [stockSearching, setStockSearching] = useState(false)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [addForm] = Form.useForm()
  const [poolForm] = Form.useForm()
  const [planForm] = Form.useForm()
  const [createPlanForm] = Form.useForm()
  const navigate = useNavigate()
  const initialLoaded = useRef(false)

  const fetchPools = async () => {
    const res = await listPools()
    setPools(res.data)
    return res.data
  }

  const fetchStocks = async (poolId: string) => {
    if (!poolId) { setStocks([]); return }
    setLoading(true)
    try {
      const res = await listStocks(poolId)
      setStocks(res.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPools().then((data) => {
      if (!initialLoaded.current && data.length > 0) {
        setActivePoolId(data[0].id)
        initialLoaded.current = true
      }
    })
  }, [])

  useEffect(() => {
    if (activePoolId) fetchStocks(activePoolId)
  }, [activePoolId])

  useEffect(() => {
    if (createPlanModalOpen) {
      getAllStocks().then((res) => setAllStocks(res.data || []))
    }
  }, [createPlanModalOpen])

  const handleAddPool = async () => {
    const name = `新观察池 ${pools.length + 1}`
    const res = await createPool({ name })
    await fetchPools()
    setActivePoolId(res.data.id)
    message.success('已创建')
  }

  const handleDeletePool = async (poolId: string) => {
    Modal.confirm({
      title: '确定删除该观察池？',
      content: '池内所有股票将一并删除',
      onOk: async () => {
        await deletePool(poolId)
        const updated = await fetchPools()
        if (activePoolId === poolId) {
          setActivePoolId(updated.length > 0 ? updated[0].id : '')
        }
        message.success('已删除')
      },
    })
  }

  const openEditPoolModal = () => {
    const pool = pools.find((p) => p.id === activePoolId)
    if (!pool) return
    poolForm.setFieldsValue({ name: pool.name, description: pool.description })
    setEditPoolModalOpen(true)
  }

  const handleEditPool = async () => {
    const values = await poolForm.validateFields()
    await updatePool(activePoolId, values)
    message.success('更新成功')
    setEditPoolModalOpen(false)
    fetchPools()
  }

  const stockSearchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const handleStockSearch = (q: string) => {
    const v = (q || '').trim()
    if (v.length < 2) {
      setStockSearchOptions([])
      return
    }
    if (stockSearchTimer.current) clearTimeout(stockSearchTimer.current)
    stockSearchTimer.current = setTimeout(() => {
      setStockSearching(true)
      searchStocks(v)
        .then((res) => {
          const list = res.data || []
          setStockSearchOptions(list.map((s) => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` })))
        })
        .catch(() => setStockSearchOptions([]))
        .finally(() => setStockSearching(false))
    }, 300)
  }

  const handleAddStock = async () => {
    const values = await addForm.validateFields()
    await addStock(activePoolId, values)
    message.success('添加成功，数据同步中...')
    setAddModalOpen(false)
    addForm.resetFields()
    setStockSearchOptions([])
    fetchStocks(activePoolId)
    fetchPools()
  }

  const handleDeleteStock = async (stockId: string) => {
    await deleteStock(activePoolId, stockId)
    message.success('已移除')
    fetchStocks(activePoolId)
    fetchPools()
  }

  const handleImport = async (file: File) => {
    const res = await importCSV(activePoolId, file)
    const r = res.data as any
    message.success(`导入 ${r.imported} 只，跳过 ${r.skipped} 只`)
    setImportModalOpen(false)
    fetchStocks(activePoolId)
    fetchPools()
    return false
  }

  const handleSync = async () => {
    if (!activePoolId) return
    setSyncing(true)
    try {
      const res = await syncPool(activePoolId)
      const taskId = res.data.task_id
      const poll = setInterval(async () => {
        try {
          const st = await getTaskStatus(taskId)
          if (st.data.status === 'completed' || st.data.status === 'failed') {
            clearInterval(poll)
            setSyncing(false)
            if (st.data.status === 'completed') {
              message.success('同步完成')
            } else {
              message.error('同步失败')
            }
            fetchStocks(activePoolId)
          }
        } catch {
          clearInterval(poll)
          setSyncing(false)
        }
      }, 2000)
    } catch {
      setSyncing(false)
    }
  }

  const handleFieldUpdate = async (stockId: string, field: string, value: any) => {
    await updateStock(activePoolId, stockId, { [field]: value } as any)
    fetchStocks(activePoolId)
  }

  const handleTogglePin = async (stock: WatchStock) => {
    await updateStock(activePoolId, stock.id, { pinned: !stock.pinned })
    fetchStocks(activePoolId)
  }

  const handleTabDragStart = (e: React.DragEvent, index: number) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
    e.dataTransfer.setData('application/json', JSON.stringify({ index }))
  }

  const handleTabDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIndex(index)
  }

  const handleTabDragLeave = () => setDragOverIndex(null)

  const handleTabDrop = async (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault()
    setDragOverIndex(null)
    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'), 10)
    if (Number.isNaN(fromIndex) || fromIndex === targetIndex) return
    const newPools = [...pools]
    const [removed] = newPools.splice(fromIndex, 1)
    newPools.splice(targetIndex, 0, removed)
    setPools(newPools)
    try {
      await reorderPools(newPools.map((p) => p.id))
      message.success('排序已保存')
    } catch {
      setPools(pools)
      message.error('排序保存失败')
    }
  }

  const handleTabDragEnd = () => setDragOverIndex(null)

  const openCreatePlanModal = (stock: WatchStock) => {
    setPlanStock(stock)
    planForm.resetFields()
    planForm.setFieldsValue({
      title: `${stock.stock_name || stock.ts_code} - 计划`,
      stocks: [{ ts_code: stock.ts_code, risk_level: 2, planned_buy_price: stock.added_price }],
    })
    setPlanModalOpen(true)
  }

  const handleCreatePlan = async () => {
    const values = await planForm.validateFields()
    const stocks = values.stocks.map((s: any) => ({
      ts_code: s.ts_code,
      risk_level: s.risk_level ?? 2,
      trigger_strategy: s.trigger_strategy,
      planned_buy_price: s.planned_buy_price,
      target_price: s.target_price,
      stop_loss_price: s.stop_loss_price,
      position_plan: s.position_plan,
      note: s.note,
    }))
    await createPlan({
      title: values.title,
      stocks,
      note: values.note,
    })
    message.success('交易计划已创建')
    setPlanModalOpen(false)
    setPlanStock(null)
  }

  const handleCreatePlanFromToolbar = async () => {
    const values = await createPlanForm.validateFields()
    const stocks = values.stocks.map((s: any) => ({
      ts_code: s.ts_code,
      risk_level: s.risk_level ?? 2,
      trigger_strategy: s.trigger_strategy,
      planned_buy_price: s.planned_buy_price,
      target_price: s.target_price,
      stop_loss_price: s.stop_loss_price,
      position_plan: s.position_plan,
      note: s.note,
    }))
    await createPlan({
      title: values.title,
      stocks,
      note: values.note,
    })
    message.success('交易计划已创建')
    setCreatePlanModalOpen(false)
    createPlanForm.resetFields()
  }

  const stockOptions = allStocks.map((s) => ({
    value: s.ts_code,
    label: `${s.stock_name || s.ts_code} (${s.ts_code})`,
  }))

  const columns = [
    {
      title: '', dataIndex: 'pinned', key: 'pinned', width: 36,
      render: (_: any, r: WatchStock) => (
        <Tooltip title={r.pinned ? '取消置顶' : '置顶'}>
          <a onClick={() => handleTogglePin(r)} style={{ color: r.pinned ? '#faad14' : '#d9d9d9', fontSize: 16 }}>
            {r.pinned ? <PushpinFilled /> : <PushpinOutlined />}
          </a>
        </Tooltip>
      ),
    },
    {
      title: '股票代码', dataIndex: 'ts_code', key: 'ts_code',
      render: (v: string) => <a onClick={() => navigate(`/stocks/${v}`)}>{v}</a>,
    },
    {
      title: '股票名称', dataIndex: 'stock_name', key: 'stock_name',
      render: (v: string, r: WatchStock) => (
        <a onClick={() => navigate(`/stocks/${r.ts_code}`)}>{v || '-'}</a>
      ),
    },
    {
      title: '最新价', dataIndex: 'latest_price', key: 'latest_price',
      render: (v: number) => v != null ? v.toFixed(2) : '-',
    },
    {
      title: '涨幅', dataIndex: 'pct_chg', key: 'pct_chg',
      render: (v: number) => {
        if (v == null) return '-'
        const color = v > 0 ? '#cf1322' : v < 0 ? '#3f8600' : '#666'
        return <span style={{ color, fontWeight: 500 }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</span>
      },
    },
    {
      title: '加入价格', dataIndex: 'added_price', key: 'added_price', width: 100,
      render: (v: number, r: WatchStock) => (
        <Input
          size="small"
          defaultValue={v != null ? String(v) : ''}
          placeholder="点击编辑"
          style={{ border: 'none', background: 'transparent', padding: '0 4px', width: 80 }}
          onFocus={(e) => { e.target.style.background = '#fff'; e.target.style.border = '1px solid #d9d9d9' }}
          onBlur={(e) => {
            e.target.style.background = 'transparent'
            e.target.style.border = 'none'
            const raw = e.target.value.trim()
            const parsed = raw ? parseFloat(raw) : NaN
            const newVal = raw === '' ? null : (Number.isFinite(parsed) ? parsed : v)
            if (newVal !== v) handleFieldUpdate(r.id, 'added_price', newVal)
          }}
          onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
        />
      ),
    },
    {
      title: '监控状态', dataIndex: 'monitor_status', key: 'monitor_status',
      render: (s: string, r: WatchStock) => (
        <Select size="small" value={s} style={{ width: 100 }} onChange={(v) => handleFieldUpdate(r.id, 'monitor_status', v)}>
          <Select.Option value="monitoring"><Tag color="green">监控中</Tag></Select.Option>
          <Select.Option value="paused"><Tag>已暂停</Tag></Select.Option>
          <Select.Option value="triggered"><Tag color="orange">已触发</Tag></Select.Option>
        </Select>
      ),
    },
    {
      title: '备注', dataIndex: 'note', key: 'note', width: 180,
      render: (v: string, r: WatchStock) => (
        <Tooltip title={v || ''} placement="topLeft">
          <Input
            size="small"
            defaultValue={v || ''}
            placeholder="点击编辑备注"
            style={{ border: 'none', background: 'transparent', padding: '0 4px' }}
            onFocus={(e) => { e.target.style.background = '#fff'; e.target.style.border = '1px solid #d9d9d9' }}
            onBlur={(e) => {
              e.target.style.background = 'transparent'
              e.target.style.border = 'none'
              const newVal = e.target.value.trim()
              if (newVal !== (v || '')) handleFieldUpdate(r.id, 'note', newVal || null)
            }}
            onPressEnter={(e) => (e.target as HTMLInputElement).blur()}
          />
        </Tooltip>
      ),
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: any, r: WatchStock) => (
        <Space size={0} split={<span style={{ color: '#d9d9d9', margin: '0 4px' }}>|</span>}>
          <Tooltip title="创建交易计划">
            <a onClick={() => openCreatePlanModal(r)}><FileAddOutlined /></a>
          </Tooltip>
          <Popconfirm title="确定移除？" onConfirm={() => handleDeleteStock(r.id)}>
            <a style={{ color: 'red' }}>移除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const activePool = pools.find((p) => p.id === activePoolId)

  const tabItems = pools.map((p) => ({
    key: p.id,
    label: `${p.name} (${p.stock_count})`,
    closable: true,
  }))

  return (
    <div>
      <Card
        title="观察池"
        styles={{ body: { padding: '0 24px 24px' } }}
        extra={activePool && (
          <Space>
            <Button size="small" type="primary" icon={<FileAddOutlined />} onClick={() => setCreatePlanModalOpen(true)}>
              创建交易计划
            </Button>
            <Button size="small" onClick={openEditPoolModal}>编辑池</Button>
            <Button size="small" icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={handleSync}>
              同步数据
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchStocks(activePoolId)}>
              刷新
            </Button>
          </Space>
        )}
      >
        <Tabs
          type="editable-card"
          activeKey={activePoolId}
          onChange={setActivePoolId}
          onEdit={(targetKey, action) => {
            if (action === 'add') handleAddPool()
            if (action === 'remove') handleDeletePool(targetKey as string)
          }}
          items={tabItems}
          style={{ marginBottom: 0 }}
          renderTabBar={() => (
            <div
              className="ant-tabs-nav-wrap"
              onDragEnd={handleTabDragEnd}
              onDragLeave={handleTabDragLeave}
            >
              <div className="ant-tabs-nav">
                <div className="ant-tabs-nav-list" style={{ display: 'flex', flexWrap: 'nowrap' }}>
                  {pools.map((p, i) => (
                    <div
                      key={p.id}
                      draggable
                      onDragStart={(e) => handleTabDragStart(e, i)}
                      onDragOver={(e) => handleTabDragOver(e, i)}
                      onDrop={(e) => handleTabDrop(e, i)}
                      className={`ant-tabs-tab ${activePoolId === p.id ? 'ant-tabs-tab-active' : ''} ${dragOverIndex === i ? 'ant-tabs-tab-drag-over' : ''}`}
                      style={{
                        cursor: 'grab',
                        userSelect: 'none',
                        display: 'flex',
                        alignItems: 'center',
                        padding: '8px 16px',
                        marginRight: 2,
                        border: '1px solid #d9d9d9',
                        borderRadius: 2,
                        background: dragOverIndex === i ? '#e6f7ff' : undefined,
                      }}
                    >
                      <HolderOutlined style={{ marginRight: 6, color: '#999', cursor: 'grab' }} />
                      <span
                        onClick={() => setActivePoolId(p.id)}
                        style={{ flex: 1, cursor: 'pointer' }}
                      >
                        {p.name} ({p.stock_count})
                      </span>
                      <span
                        className="ant-tabs-tab-remove"
                        onClick={(e) => { e.stopPropagation(); handleDeletePool(p.id) }}
                        style={{ marginLeft: 8, cursor: 'pointer', fontSize: 12 }}
                      >
                        ×
                      </span>
                    </div>
                  ))}
                  <div
                    className="ant-tabs-tab-add"
                    onClick={handleAddPool}
                    style={{
                      padding: '8px 16px',
                      border: '1px dashed #d9d9d9',
                      borderRadius: 2,
                      cursor: 'pointer',
                      marginLeft: 2,
                    }}
                  >
                    +
                  </div>
                </div>
              </div>
            </div>
          )}
        />

        {activePool && (
          <>
            {activePool.description && (
              <p style={{ color: '#888', margin: '8px 0' }}>{activePool.description}</p>
            )}
            <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Button size="small" icon={<UploadOutlined />} onClick={() => setImportModalOpen(true)}>CSV 导入</Button>
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>添加股票</Button>
            </div>
            <Table dataSource={stocks} columns={columns} rowKey="id" loading={loading} size="small" pagination={false} />
          </>
        )}

        {pools.length === 0 && (
          <div style={{ textAlign: 'center', padding: 48, color: '#999' }}>
            暂无观察池，点击上方 "+" 创建
          </div>
        )}
      </Card>

      {/* 添加股票 */}
      <Modal title="添加股票" open={addModalOpen} onOk={handleAddStock} onCancel={() => { setAddModalOpen(false); setStockSearchOptions([]) }}>
        <Form form={addForm} layout="vertical">
          <Form.Item name="ts_code" label="股票" rules={[{ required: true, message: '请输入股票代码或名称' }]}>
            <AutoComplete
              options={stockSearchOptions}
              placeholder="输入代码或名称搜索，如 000001 或 平安银行"
              onSearch={handleStockSearch}
              notFoundContent={stockSearching ? '搜索中...' : (stockSearchOptions.length === 0 ? '输入至少2个字符搜索，或直接输入6位代码' : null)}
            />
          </Form.Item>
          <Form.Item name="added_price" label="加入价格">
            <InputNumber style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑观察池 */}
      <Modal title="编辑观察池" open={editPoolModalOpen} onOk={handleEditPool} onCancel={() => setEditPoolModalOpen(false)}>
        <Form form={poolForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建交易计划 */}
      <Modal title={`创建交易计划 - ${planStock?.stock_name || planStock?.ts_code || ''}`} open={planModalOpen} onOk={handleCreatePlan} onCancel={() => { setPlanModalOpen(false); setPlanStock(null) }} width={560}>
        <Form form={planForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name={['stocks', 0, 'ts_code']} hidden><Input /></Form.Item>
          <Form.Item noStyle shouldUpdate>
            {() => (
              <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 8 }}>
                <div style={{ marginBottom: 8 }}>股票：{planStock?.stock_name || planStock?.ts_code || '-'}</div>
                <Form.Item name={['stocks', 0, 'trigger_strategy']} label="触发策略">
                  <AutoComplete options={['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合'].map((o) => ({ value: o }))} placeholder="输入或选择" />
                </Form.Item>
                <Space wrap>
                  <Form.Item name={['stocks', 0, 'planned_buy_price']} label="计划买入价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name={['stocks', 0, 'target_price']} label="目标价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name={['stocks', 0, 'stop_loss_price']} label="止损价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                </Space>
                <Form.Item name={['stocks', 0, 'position_plan']} label="仓位(%)">
                  <InputNumber min={0} max={100} addonAfter="%" style={{ width: 140 }} />
                </Form.Item>
                <Form.Item name={['stocks', 0, 'risk_level']} label="风险程度">
                  <Select style={{ width: 120 }} options={[
                    { value: 1, label: '低风险' },
                    { value: 2, label: '中风险' },
                    { value: 3, label: '高风险' },
                  ]} />
                </Form.Item>
                <Form.Item name={['stocks', 0, 'note']} label="备注">
                  <Input.TextArea rows={2} />
                </Form.Item>
              </div>
            )}
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      {/* CSV 导入 */}
      <Modal title="CSV 批量导入" open={importModalOpen} footer={null} onCancel={() => setImportModalOpen(false)}>
        <p>CSV 文件格式：必须包含 <code>ts_code</code>（或 <code>股票代码</code>/<code>code</code>）列，输入6位代码即可。可选 <code>added_price</code>、<code>note</code> 列</p>
        <Upload.Dragger
          accept=".csv"
          showUploadList={false}
          beforeUpload={(file) => { handleImport(file); return false }}
        >
          <p>点击或拖拽 CSV 文件到此处</p>
        </Upload.Dragger>
      </Modal>

      {/* 工具栏创建交易计划 */}
      <Modal title="新建交易计划" open={createPlanModalOpen} onOk={handleCreatePlanFromToolbar} onCancel={() => { setCreatePlanModalOpen(false); createPlanForm.resetFields() }} width={900}>
        <Form form={createPlanForm} layout="vertical" initialValues={{ stocks: [{ risk_level: 2 }] }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="股票列表">
            <Form.List name="stocks" rules={[{ validator: (_, v) => (v?.length ? Promise.resolve() : Promise.reject('至少添加一只股票')) }]}>
              {(fields, { add, remove }) => (
                <>
                  <Table
                    dataSource={fields}
                    rowKey={(f) => String(f.key)}
                    pagination={false}
                    size="small"
                    scroll={{ x: 1100 }}
                    columns={[
                      {
                        title: '股票',
                        key: 'ts_code',
                        width: 180,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true, message: '请选择' }]}>
                            <Select
                              showSearch
                              placeholder="选择或搜索"
                              size="small"
                              style={{ width: 160 }}
                              options={stockOptions}
                              filterOption={(input, opt) =>
                                (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
                              }
                            />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '触发策略',
                        key: 'trigger_strategy',
                        width: 130,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle>
                            <AutoComplete options={TRIGGER_OPTIONS.map((o) => ({ value: o }))} placeholder="输入或选择" size="small" style={{ width: 120 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '买入价',
                        key: 'planned_buy_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '目标价',
                        key: 'target_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'target_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '止损价',
                        key: 'stop_loss_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '仓位(%)',
                        key: 'position_plan',
                        width: 90,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'position_plan']} noStyle>
                            <InputNumber size="small" min={0} max={100} addonAfter="%" style={{ width: 80 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '风险',
                        key: 'risk_level',
                        width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'risk_level']} noStyle>
                            <Select size="small" style={{ width: 90 }} options={[
                              { value: 1, label: '低风险' },
                              { value: 2, label: '中风险' },
                              { value: 3, label: '高风险' },
                            ]} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '备注',
                        key: 'note',
                        width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'note']} noStyle>
                            <Input placeholder="备注" size="small" />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '',
                        key: 'action',
                        width: 40,
                        render: (_, __, i) => fields.length > 1 ? <a onClick={() => remove(fields[i].name)} style={{ color: '#ff4d4f' }}>删</a> : null,
                      },
                    ]}
                  />
                  <Button type="dashed" onClick={() => add({ risk_level: 2 })} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加股票</Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PoolList
