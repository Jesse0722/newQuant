import React, { useState } from 'react'
import { Layout, Menu } from 'antd'
import {
  DashboardOutlined,
  EyeOutlined,
  AlertOutlined,
  FileTextOutlined,
  FilterOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'

const { Sider, Content, Header } = Layout

const menuItems = [
  { key: '/', icon: <DashboardOutlined />, label: '仪表盘' },
  { key: '/pools', icon: <EyeOutlined />, label: '观察池' },
  { key: '/strategy', icon: <FilterOutlined />, label: '策略选股' },
  { key: '/data', icon: <DatabaseOutlined />, label: '数据管理' },
  { key: '/alerts', icon: <AlertOutlined />, label: '监控提醒' },
  { key: '/plans', icon: <FileTextOutlined />, label: '交易计划' },
]

const MainLayout: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  const selectedKey = '/' + (location.pathname.split('/')[1] || '')

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed}>
        <div style={{ height: 32, margin: 16, color: '#fff', fontSize: 18, textAlign: 'center', fontWeight: 'bold' }}>
          {collapsed ? 'Q' : '量化交易'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header style={{ padding: '0 24px', background: '#fff', borderBottom: '1px solid #f0f0f0' }}>
          <h3 style={{ margin: 0, lineHeight: '64px' }}>量化交易工作流管理系统</h3>
        </Header>
        <Content style={{ margin: 24 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}

export default MainLayout
