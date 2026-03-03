import React, { useEffect, useState, useRef } from 'react'
import {
  Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Space,
  Tag, Upload, message, Popconfirm, Select, Tooltip,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, SyncOutlined, ReloadOutlined,
  PushpinOutlined, PushpinFilled, FileAddOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  listPools, createPool, updatePool, deletePool,
  listStocks, addStock, deleteStock, updateStock, importCSV,
} from '../../api/pools'
import { createPlan } from '../../api/plans'
import { syncPool, getTaskStatus } from '../../api/sync'
import type { Pool, WatchStock } from '../../types'

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
  const [syncing, setSyncing] = useState(false)
  const [addForm] = Form.useForm()
  const [poolForm] = Form.useForm()
  const [planForm] = Form.useForm()
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

  const handleAddStock = async () => {
    const values = await addForm.validateFields()
    await addStock(activePoolId, values)
    message.success('添加成功，数据同步中...')
    setAddModalOpen(false)
    addForm.resetFields()
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

  const openCreatePlanModal = (stock: WatchStock) => {
    setPlanStock(stock)
    planForm.resetFields()
    planForm.setFieldsValue({
      ts_code: stock.ts_code,
      plan_type: 'trend',
      risk_level: 3,
    })
    setPlanModalOpen(true)
  }

  const handleCreatePlan = async () => {
    const values = await planForm.validateFields()
    await createPlan(values)
    message.success('交易计划已创建')
    setPlanModalOpen(false)
    setPlanStock(null)
  }

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
      title: '加入价格', dataIndex: 'added_price', key: 'added_price',
      render: (v: number, r: WatchStock) => (
        <InputNumber
          size="small"
          value={v}
          style={{ width: 90 }}
          controls={false}
          onBlur={(e) => {
            const newVal = e.target.value ? parseFloat(e.target.value) : null
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
      <Modal title="添加股票" open={addModalOpen} onOk={handleAddStock} onCancel={() => setAddModalOpen(false)}>
        <Form form={addForm} layout="vertical">
          <Form.Item name="ts_code" label="股票代码" rules={[{ required: true, message: '请输入股票代码' }]}>
            <Input placeholder="输入6位代码，如 000001" />
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
      <Modal title={`创建交易计划 - ${planStock?.stock_name || planStock?.ts_code || ''}`} open={planModalOpen} onOk={handleCreatePlan} onCancel={() => { setPlanModalOpen(false); setPlanStock(null) }} width={600}>
        <Form form={planForm} layout="vertical" initialValues={{ risk_level: 3, plan_type: 'trend' }}>
          <Form.Item name="ts_code" hidden><Input /></Form.Item>
          <Form.Item name="plan_type" label="计划类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'trend', label: '趋势跟踪' },
              { value: 'short_term', label: '短线操作' },
              { value: 'event_driven', label: '事件驱动' },
            ]} />
          </Form.Item>
          <Form.Item name="risk_level" label="风险等级">
            <InputNumber min={1} max={5} />
          </Form.Item>
          <Form.Item name="trigger_strategy" label="触发策略">
            <Input.TextArea placeholder="如：MACD 金叉触发" rows={2} />
          </Form.Item>
          <Form.Item name="event_note" label="热点/事件">
            <Input.TextArea placeholder="宏观背景、事件驱动原因" rows={2} />
          </Form.Item>
          <Space>
            <Form.Item name="planned_buy_price" label="计划买入价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
            <Form.Item name="target_price" label="目标价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
            <Form.Item name="stop_loss_price" label="止损价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
          </Space>
          <Form.Item name="note" label="备注">
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
    </div>
  )
}

export default PoolList
