import React, { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Card, Space, Popconfirm, message } from 'antd'
import { PlusOutlined, EditOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listPools, createPool, updatePool, deletePool } from '../../api/pools'
import type { Pool } from '../../types'

const PoolList: React.FC = () => {
  const [pools, setPools] = useState<Pool[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingPool, setEditingPool] = useState<Pool | null>(null)
  const [form] = Form.useForm()
  const navigate = useNavigate()

  const fetchPools = () => {
    setLoading(true)
    listPools().then((res) => setPools(res.data)).finally(() => setLoading(false))
  }

  useEffect(() => { fetchPools() }, [])

  const openCreateModal = () => {
    setEditingPool(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEditModal = (pool: Pool) => {
    setEditingPool(pool)
    form.setFieldsValue({ name: pool.name, description: pool.description })
    setModalOpen(true)
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    if (editingPool) {
      await updatePool(editingPool.id, values)
      message.success('更新成功')
    } else {
      await createPool(values)
      message.success('创建成功')
    }
    setModalOpen(false)
    form.resetFields()
    setEditingPool(null)
    fetchPools()
  }

  const handleDelete = async (id: string) => {
    await deletePool(id)
    message.success('已删除')
    fetchPools()
  }

  const columns = [
    { title: '名称', dataIndex: 'name', key: 'name',
      render: (name: string, r: Pool) => <a onClick={() => navigate(`/pools/${r.id}`)}>{name}</a> },
    { title: '描述', dataIndex: 'description', key: 'description', render: (v: string) => v || '-' },
    { title: '股票数量', dataIndex: 'stock_count', key: 'stock_count' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
    {
      title: '操作',
      key: 'action',
      render: (_: any, r: Pool) => (
        <Space>
          <a onClick={() => navigate(`/pools/${r.id}`)}>查看</a>
          <a onClick={() => openEditModal(r)}>编辑</a>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <a style={{ color: 'red' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="观察池"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>新建观察池</Button>}
    >
      <Table dataSource={pools} columns={columns} rowKey="id" loading={loading} />
      <Modal
        title={editingPool ? '编辑观察池' : '新建观察池'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => { setModalOpen(false); setEditingPool(null) }}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：短线池、趋势跟踪" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default PoolList
