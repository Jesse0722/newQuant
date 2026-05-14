import React, { useEffect } from 'react'
import { Button, Form, Input, Typography, message } from 'antd'
import { LockOutlined, RiseOutlined, SafetyCertificateOutlined, UserOutlined } from '@ant-design/icons'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { getAuthSession, login } from '../../auth/session'
import './LoginPage.css'

interface LoginFormValues {
  username: string
  password: string
}

interface LocationState {
  from?: string
}

const LoginPage: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [form] = Form.useForm<LoginFormValues>()
  const authed = Boolean(getAuthSession())
  const from = (location.state as LocationState | null)?.from || '/'

  useEffect(() => {
    form.setFieldsValue({ username: 'admin' })
  }, [form])

  if (authed) {
    return <Navigate to="/" replace />
  }

  const handleFinish = (values: LoginFormValues) => {
    const session = login(values.username, values.password)
    if (!session) {
      message.error('账号或密码错误')
      return
    }
    message.success('登录成功')
    navigate(from, { replace: true })
  }

  return (
    <div className="login-page">
      <div className="login-shell">
        <section className="login-hero" aria-label="星枢 Quant 工作台介绍">
          <div>
            <div className="login-brand">
              <div className="login-logo">
                <RiseOutlined />
              </div>
              <div>
                <div style={{ fontSize: 20, fontWeight: 800 }}>星枢 Quant</div>
                <div className="login-kicker">AI Quant Workflow</div>
              </div>
            </div>

            <h1 className="login-title">
              策略、舆情、买点与计划的一体化交易工作台
            </h1>
            <p className="login-copy">
              每日聚合行情、题材机会与买点雷达，把“为什么关注、什么时候行动、交易后如何复盘”沉淀成清晰流程。
            </p>

            <div className="login-metrics">
              <div className="login-metric">
                <strong>Radar</strong>
                <span>买点扫描</span>
              </div>
              <div className="login-metric">
                <strong>Signal</strong>
                <span>消息机会</span>
              </div>
              <div className="login-metric">
                <strong>Plan</strong>
                <span>交易闭环</span>
              </div>
            </div>
          </div>

          <div className="login-strip" aria-hidden="true">
            <div className="login-strip-row">
              <span>趋势确认</span>
              <div className="login-bar"><i style={{ width: '78%' }} /></div>
              <span className="mono">78%</span>
            </div>
            <div className="login-strip-row">
              <span>舆情热度</span>
              <div className="login-bar"><i style={{ width: '86%' }} /></div>
              <span className="mono">86%</span>
            </div>
            <div className="login-strip-row">
              <span>风控纪律</span>
              <div className="login-bar"><i style={{ width: '92%' }} /></div>
              <span className="mono">92%</span>
            </div>
          </div>
        </section>

        <section className="login-panel" aria-label="登录表单">
          <SafetyCertificateOutlined style={{ color: 'var(--accent)', fontSize: 28, marginBottom: 14 }} />
          <Typography.Title level={1}>登录工作台</Typography.Title>
          <div className="login-panel-subtitle">进入星枢 Quant 工作台</div>

          <Form
            form={form}
            layout="vertical"
            size="large"
            requiredMark={false}
            onFinish={handleFinish}
          >
            <Form.Item name="username" label="账号" rules={[{ required: true, message: '请输入账号' }]}>
              <Input prefix={<UserOutlined />} placeholder="admin" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="请输入密码" autoComplete="current-password" />
            </Form.Item>
            <Button type="primary" htmlType="submit" block data-testid="login-submit" style={{ height: 44, marginTop: 8 }}>
              登录
            </Button>
          </Form>

          <div className="login-hint">
            本登录仅用于本地 MVP 入口保护。
          </div>
          <div className="login-footer">星枢 QUANT · LOCAL SECURE ENTRY</div>
        </section>
      </div>
    </div>
  )
}

export default LoginPage
