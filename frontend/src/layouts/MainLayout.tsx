import React, { useCallback, useState, useEffect } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import {
  DashboardOutlined,
  EyeOutlined,
  AlertOutlined,
  FileTextOutlined,
  FilterOutlined,
  DatabaseOutlined,
  RadarChartOutlined,
  MessageOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  RiseOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { logout } from '../auth/session'
import { getAlertsPendingCount } from '../api/alerts'

/* ────────────────────────────────────────────────
   Navigation config
──────────────────────────────────────────────── */
interface NavItem {
  key: string
  icon: React.ReactNode
  label: string
  badge?: number
}

const navItems: NavItem[] = [
  { key: '/',          icon: <DashboardOutlined />,  label: '仪表盘' },
  { key: '/pools',     icon: <EyeOutlined />,        label: '观察池' },
  { key: '/buy-radar', icon: <RadarChartOutlined />, label: '买点雷达' },
  { key: '/messages',  icon: <MessageOutlined />,    label: '消息中心' },
  { key: '/alerts',    icon: <AlertOutlined />,      label: '买点提醒' },
  { key: '/strategy',  icon: <FilterOutlined />,     label: '策略选股' },
  { key: '/plans',     icon: <FileTextOutlined />,   label: '交易计划' },
  { key: '/data',      icon: <DatabaseOutlined />,   label: '数据管理' },
]

const pageTitle: Record<string, string> = {
  '/':          '仪表盘',
  '/pools':     '观察池',
  '/buy-radar': '买点雷达',
  '/messages':  '消息中心',
  '/alerts':    '买点提醒',
  '/strategy':  '策略选股',
  '/plans':     '交易计划',
  '/data':      '数据管理',
}

/* ────────────────────────────────────────────────
   Clock component
──────────────────────────────────────────────── */
const LiveClock: React.FC = () => {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const fmt = (n: number) => String(n).padStart(2, '0')
  const h = fmt(now.getHours())
  const m = fmt(now.getMinutes())
  const s = fmt(now.getSeconds())
  const dateStr = now.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', weekday: 'short' })
  return (
    <div style={{ textAlign: 'right' }}>
      <div className="mono" style={{ fontSize: 18, fontWeight: 600, color: 'var(--accent)', letterSpacing: '0.08em' }}>
        {h}<span style={{ opacity: 0.5, animation: 'pulse-clock 1s infinite' }}>:</span>{m}
        <span style={{ fontSize: 13, opacity: 0.6 }}> :{s}</span>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 1 }}>{dateStr}</div>
    </div>
  )
}

/* ────────────────────────────────────────────────
   Market status
──────────────────────────────────────────────── */
const MarketStatus: React.FC = () => {
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const totalMin = h * 60 + m
  const isWeekday = now.getDay() >= 1 && now.getDay() <= 5
  const isOpen = isWeekday && (
    (totalMin >= 9 * 60 + 30 && totalMin < 11 * 60 + 30) ||
    (totalMin >= 13 * 60 && totalMin < 15 * 60)
  )
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6,
      padding: '4px 12px', borderRadius: 20,
      background: isOpen ? 'var(--color-up-dim)' : 'rgba(255,255,255,0.05)',
      border: `1px solid ${isOpen ? 'rgba(0,230,118,0.3)' : 'var(--border-default)'}`,
    }}>
      <span className={`dot ${isOpen ? 'dot-up' : 'dot-muted'}`} />
      <span style={{ fontSize: 12, color: isOpen ? 'var(--color-up)' : 'var(--text-muted)', fontWeight: 500 }}>
        {isOpen ? 'A股交易中' : '已休市'}
      </span>
    </div>
  )
}

/* ────────────────────────────────────────────────
   Main Layout
──────────────────────────────────────────────── */
const MainLayout: React.FC = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [pendingAlertCount, setPendingAlertCount] = useState(0)

  const selectedKey = '/' + (location.pathname.split('/')[1] || '')
  const title = pageTitle[selectedKey] ?? '星枢 Quant'

  const refreshPendingAlertCount = useCallback(() => {
    getAlertsPendingCount({ source: 'buy_radar' })
      .then((res) => setPendingAlertCount(res.data.count))
      .catch(() => setPendingAlertCount(0))
  }, [])

  useEffect(() => {
    refreshPendingAlertCount()
  }, [location.pathname, refreshPendingAlertCount])

  useEffect(() => {
    const handleFocus = () => refreshPendingAlertCount()
    const handleAlertChange = () => refreshPendingAlertCount()
    window.addEventListener('focus', handleFocus)
    window.addEventListener('buy-alerts:changed', handleAlertChange)
    return () => {
      window.removeEventListener('focus', handleFocus)
      window.removeEventListener('buy-alerts:changed', handleAlertChange)
    }
  }, [refreshPendingAlertCount])

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div style={{ display: 'flex', height: '100vh', background: 'var(--bg-base)', overflow: 'hidden' }}>
      {/* ── Sidebar ── */}
      <aside style={{
        width: collapsed ? 'var(--sidebar-collapsed-width)' : 'var(--sidebar-width)',
        flexShrink: 0,
        background: 'var(--bg-sidebar)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width var(--transition-base)',
        overflow: 'hidden',
        position: 'relative',
        zIndex: 10,
      }}>
        {/* Sidebar top glow */}
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: 1,
          background: 'linear-gradient(90deg, transparent, var(--accent), transparent)',
        }} />

        {/* Logo */}
        <div style={{
          height: 'var(--topbar-height)',
          display: 'flex', alignItems: 'center',
          padding: collapsed ? '0 20px' : '0 20px',
          borderBottom: '1px solid var(--border-subtle)',
          gap: 10, flexShrink: 0, overflow: 'hidden',
        }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8, flexShrink: 0,
            background: 'linear-gradient(135deg, #00d4ff 0%, #0080ff 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 12px rgba(0,212,255,0.4)',
          }}>
            <RiseOutlined style={{ color: '#fff', fontSize: 16 }} />
          </div>
          {!collapsed && (
            <div style={{ overflow: 'hidden' }}>
              <div style={{
                fontSize: 15, fontWeight: 700, whiteSpace: 'nowrap',
                background: 'linear-gradient(90deg, #00d4ff, #0080ff)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
              }}>
                星枢 Quant
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap', marginTop: -2 }}>
                QUANT WORKFLOW
              </div>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav style={{ flex: 1, padding: '12px 8px', overflowY: 'auto', overflowX: 'hidden' }}>
          {navItems.map((item) => {
            const isActive = selectedKey === item.key
            const badge = item.key === '/alerts' ? pendingAlertCount : item.badge
            return (
              <button
                key={item.key}
                onClick={() => navigate(item.key)}
                title={collapsed ? item.label : undefined}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center',
                  gap: 10, padding: collapsed ? '10px 14px' : '10px 12px',
                  marginBottom: 2, border: 'none', cursor: 'pointer',
                  borderRadius: 8, background: 'transparent',
                  position: 'relative', overflow: 'hidden',
                  transition: 'all var(--transition-fast)',
                  color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
                  ...(isActive ? {
                    background: 'rgba(0,212,255,0.08)',
                  } : {}),
                }}
                onMouseEnter={(e) => {
                  if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(0,212,255,0.05)'
                  ;(e.currentTarget as HTMLButtonElement).style.color = isActive ? 'var(--accent)' : 'var(--text-primary)'
                }}
                onMouseLeave={(e) => {
                  if (!isActive) (e.currentTarget as HTMLButtonElement).style.background = 'transparent'
                  ;(e.currentTarget as HTMLButtonElement).style.color = isActive ? 'var(--accent)' : 'var(--text-secondary)'
                }}
              >
                {/* Active indicator */}
                {isActive && (
                  <div style={{
                    position: 'absolute', left: 0, top: '50%', transform: 'translateY(-50%)',
                    width: 3, height: 20, borderRadius: '0 3px 3px 0',
                    background: 'var(--accent)',
                    boxShadow: '0 0 8px var(--accent)',
                  }} />
                )}

                {/* Icon */}
                <span style={{ fontSize: 16, flexShrink: 0, width: 20, textAlign: 'center' }}>
                  {item.icon}
                </span>

                {/* Label + Badge */}
                {!collapsed && (
                  <>
                    <span style={{ fontSize: 13, fontWeight: isActive ? 600 : 400, flex: 1, textAlign: 'left', whiteSpace: 'nowrap' }}>
                      {item.label}
                    </span>
                    {badge != null && badge > 0 && (
                      <span className="badge badge-down" style={{ fontSize: 10, minWidth: 18, height: 18 }}>
                        {badge}
                      </span>
                    )}
                  </>
                )}
              </button>
            )
          })}
        </nav>

        {/* Bottom: Settings + Collapse */}
        <div style={{ padding: '8px', borderTop: '1px solid var(--border-subtle)', flexShrink: 0 }}>
          <button
            onClick={handleLogout}
            style={{
              width: '100%', display: 'flex', alignItems: 'center',
              gap: 10, padding: collapsed ? '10px 14px' : '10px 12px',
              marginBottom: 4, border: 'none', cursor: 'pointer',
              borderRadius: 8, background: 'transparent',
              color: 'var(--text-muted)',
              transition: 'all var(--transition-fast)',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.05)'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-primary)' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)' }}
          >
            <LogoutOutlined style={{ fontSize: 16, flexShrink: 0, width: 20, textAlign: 'center' }} />
            {!collapsed && <span style={{ fontSize: 13 }}>退出登录</span>}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            style={{
              width: '100%', display: 'flex', alignItems: 'center',
              gap: 10, padding: collapsed ? '10px 14px' : '10px 12px',
              border: 'none', cursor: 'pointer',
              borderRadius: 8, background: 'transparent',
              color: 'var(--text-muted)',
              transition: 'all var(--transition-fast)',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.05)'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-primary)' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = 'transparent'; (e.currentTarget as HTMLButtonElement).style.color = 'var(--text-muted)' }}
          >
            {collapsed
              ? <MenuUnfoldOutlined style={{ fontSize: 16, width: 20, textAlign: 'center' }} />
              : <MenuFoldOutlined   style={{ fontSize: 16, width: 20, textAlign: 'center' }} />
            }
            {!collapsed && <span style={{ fontSize: 13 }}>收起侧边栏</span>}
          </button>
        </div>
      </aside>

      {/* ── Main Area ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {/* Topbar */}
        <header style={{
          height: 'var(--topbar-height)',
          display: 'flex', alignItems: 'center',
          padding: '0 24px',
          background: 'rgba(13,21,38,0.8)',
          backdropFilter: 'blur(12px)',
          borderBottom: '1px solid var(--border-subtle)',
          flexShrink: 0, gap: 16,
          position: 'sticky', top: 0, zIndex: 9,
        }}>
          {/* Page title */}
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
              {title}
            </h1>
          </div>

          {/* Right side widgets */}
          <MarketStatus />
          <div style={{ width: 1, height: 32, background: 'var(--border-default)' }} />
          <LiveClock />
        </header>

        {/* Page content */}
        <main style={{
          flex: 1,
          overflow: 'auto',
          padding: '24px',
          background: 'var(--bg-base)',
        }}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default MainLayout
