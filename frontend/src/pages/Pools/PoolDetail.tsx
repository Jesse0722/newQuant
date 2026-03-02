import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Button, Modal, Form, Input, InputNumber, Space, Tag, Upload, message, Popconfirm, Progress, Select } from 'antd'
import { PlusOutlined, UploadOutlined, SyncOutlined, ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { getPool, listStocks, addStock, deleteStock, updateStock, updatePool, importCSV } from '../../api/pools'
import { syncPool } from '../../api/sync'
import { getTaskStatus } from '../../api/sync'
import type { Pool, WatchStock } from '../../types'

const PoolDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [pool, setPool] = useState<Pool | null>(null)
  const [stocks, setStocks] = useState<WatchStock[]>([])
  const [loading, setLoading] = useState(true)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [editPoolModalOpen, setEditPoolModalOpen] = useState(false)
  const [editStockModalOpen, setEditStockModalOpen] = useState(false)
  const [editingStock, setEditingStock] = useState<WatchStock | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState(0)
  const [form] = Form.useForm()
  const [poolForm] = Form.useForm()
  const [stockForm] = Form.useForm()

  const fetchData = () => {
    if (!id) return
    setLoading(true)
    Promise.all([getPool(id), listStocks(id)])
      .then(([poolRes, stocksRes]) => {
        setPool(poolRes.data)
        setStocks(stocksRes.data)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [id])

  const handleAddStock = async () => {
    const values = await form.validateFields()
    await addStock(id!, values)
    message.success('添加成功')
    setAddModalOpen(false)
    form.resetFields()
    fetchData()
  }

  const handleDeleteStock = async (stockId: string) => {
    await deleteStock(id!, stockId)
    message.success('已移除')
    fetchData()
  }

  const handleImport = async (file: File) => {
    const res = await importCSV(id!, file)
    const r = res.data as any
    message.success(`导入 ${r.imported} 只，跳过 ${r.skipped} 只`)
    setImportModalOpen(false)
    fetchData()
    return false
  }

  const handleSync = async () => {
    if (!id) return
    setSyncing(true)
    setSyncProgress(0)
    const res = await syncPool(id)
    const taskId = res.data.task_id
    const poll = setInterval(async () => {
      try {
        const st = await getTaskStatus(taskId)
        setSyncProgress(Math.round(st.data.progress * 100))
        if (st.data.status === 'completed' || st.data.status === 'failed') {
          clearInterval(poll)
          setSyncing(false)
          if (st.data.status === 'completed') {
            message.success('同步完成')
          } else {
            message.error('同步失败: ' + st.data.message)
          }
          fetchData()
        }
      } catch {
        clearInterval(poll)
        setSyncing(false)
      }
    }, 2000)
  }

  const handleStatusChange = async (stockId: string, status: string) => {
    await updateStock(id!, stockId, { monitor_status: status })
    fetchData()
  }

  const openEditPoolModal = () => {
    if (!pool) return
    poolForm.setFieldsValue({ name: pool.name, description: pool.description })
    setEditPoolModalOpen(true)
  }

  const handleEditPool = async () => {
    const values = await poolForm.validateFields()
    await updatePool(id!, values)
    message.success('更新成功')
    setEditPoolModalOpen(false)
    fetchData()
  }

  const openEditStockModal = (stock: WatchStock) => {
    setEditingStock(stock)
    stockForm.setFieldsValue({ note: stock.note, monitor_status: stock.monitor_status })
    setEditStockModalOpen(true)
  }

  const handleEditStock = async () => {
    if (!editingStock) return
    const values = await stockForm.validateFields()
    await updateStock(id!, editingStock.id, values)
    message.success('更新成功')
    setEditStockModalOpen(false)
    setEditingStock(null)
    fetchData()
  }

  const columns = [
    { title: '股票代码', dataIndex: 'ts_code', key: 'ts_code' },
    { title: '股票名称', dataIndex: 'stock_name', key: 'stock_name', render: (v: string) => v || '-' },
    { title: '加入价格', dataIndex: 'added_price', key: 'added_price', render: (v: number) => v?.toFixed(2) || '-' },
    { title: '来源', dataIndex: 'source', key: 'source', render: (v: string) => ({ manual: '手动', csv: 'CSV' }[v] || v) },
    {
      title: '监控状态',
      dataIndex: 'monitor_status',
      key: 'monitor_status',
      render: (s: string, r: WatchStock) => (
        <Select size="small" value={s} style={{ width: 100 }} onChange={(v) => handleStatusChange(r.id, v)}>
          <Select.Option value="monitoring"><Tag color="green">监控中</Tag></Select.Option>
          <Select.Option value="paused"><Tag>已暂停</Tag></Select.Option>
          <Select.Option value="triggered"><Tag color="orange">已触发</Tag></Select.Option>
        </Select>
      ),
    },
    { title: '备注', dataIndex: 'note', key: 'note', render: (v: string) => v || '-' },
    { title: '加入时间', dataIndex: 'added_at', key: 'added_at', render: (v: string) => v?.slice(0, 10) },
    {
      title: '操作',
      key: 'action',
      render: (_: any, r: WatchStock) => (
        <Space>
          <a onClick={() => openEditStockModal(r)}>编辑</a>
          <Popconfirm title="确定移除？" onConfirm={() => handleDeleteStock(r.id)}>
            <a style={{ color: 'red' }}>移除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} style={{ marginBottom: 16 }} onClick={() => navigate('/pools')}>
        返回列表
      </Button>
      <Card
        title={
          <Space>
            {pool?.name || '加载中...'}
            <Button type="text" size="small" icon={<EditOutlined />} onClick={openEditPoolModal} />
          </Space>
        }
        extra={
          <Space>
            <Button icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={handleSync}>
              同步数据
            </Button>
            <Button icon={<UploadOutlined />} onClick={() => setImportModalOpen(true)}>
              CSV 导入
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>
              添加股票
            </Button>
          </Space>
        }
      >
        {pool?.description && <p style={{ color: '#888' }}>{pool.description}</p>}
        {syncing && <Progress percent={syncProgress} style={{ marginBottom: 16 }} />}
        <Table dataSource={stocks} columns={columns} rowKey="id" loading={loading} />
      </Card>

      <Modal title="添加股票" open={addModalOpen} onOk={handleAddStock} onCancel={() => setAddModalOpen(false)}>
        <Form form={form} layout="vertical">
          <Form.Item name="ts_code" label="股票代码" rules={[{ required: true, message: '请输入股票代码，如 000001' }]}>
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

      <Modal title="编辑观察池" open={editPoolModalOpen} onOk={handleEditPool} onCancel={() => setEditPoolModalOpen(false)}>
        <Form form={poolForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑股票" open={editStockModalOpen} onOk={handleEditStock} onCancel={() => { setEditStockModalOpen(false); setEditingStock(null) }}>
        <Form form={stockForm} layout="vertical">
          <Form.Item label="股票">
            <Input disabled value={editingStock ? `${editingStock.ts_code} ${editingStock.stock_name || ''}` : ''} />
          </Form.Item>
          <Form.Item name="monitor_status" label="监控状态">
            <Select>
              <Select.Option value="monitoring">监控中</Select.Option>
              <Select.Option value="paused">已暂停</Select.Option>
              <Select.Option value="triggered">已触发</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea placeholder="如：关注理由、买入条件等" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="CSV 批量导入" open={importModalOpen} footer={null} onCancel={() => setImportModalOpen(false)}>
        <p>CSV 文件格式：必须包含 <code>ts_code</code>（或 <code>股票代码</code>/<code>code</code>）列，输入6位代码即可（如 000001），系统会自动补全交易所后缀。可选 <code>added_price</code>、<code>note</code> 列</p>
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

export default PoolDetail
