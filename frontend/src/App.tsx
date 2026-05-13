import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/Dashboard'
import PoolList from './pages/Pools/PoolList'
import Alerts from './pages/Alerts'
import PlanList from './pages/Plans/PlanList'
import PlanRedirect from './pages/Plans/PlanRedirect'
import StockDetail from './pages/Stocks/StockDetail'
import StrategyPage from './pages/Strategy/StrategyPage'
import BuyRadarPage from './pages/BuyRadar/BuyRadarPage'
import DataPage from './pages/Data/DataPage'
import './index.css'

const { darkAlgorithm } = antdTheme

function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: darkAlgorithm,
        token: {
          // Brand colors
          colorPrimary: '#00d4ff',
          colorSuccess: '#00e676',
          colorWarning: '#ffa502',
          colorError: '#ff4757',
          colorInfo: '#00d4ff',

          // Background
          colorBgBase: '#070c18',
          colorBgContainer: '#111e35',
          colorBgElevated: '#0f1a2e',
          colorBgLayout: '#070c18',
          colorBgSpotlight: '#152240',

          // Border
          colorBorder: 'rgba(255,255,255,0.08)',
          colorBorderSecondary: 'rgba(255,255,255,0.04)',

          // Text
          colorText: '#e8edf8',
          colorTextSecondary: '#8899bb',
          colorTextTertiary: '#4a5a7a',
          colorTextDisabled: '#2a3a5a',
          colorTextLightSolid: '#e8edf8',

          // Typography
          fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          fontSize: 14,
          fontSizeHeading1: 28,
          fontSizeHeading2: 22,
          fontSizeHeading3: 18,
          fontSizeHeading4: 16,
          fontSizeHeading5: 14,

          // Shape
          borderRadius: 10,
          borderRadiusSM: 6,
          borderRadiusLG: 14,
          borderRadiusXS: 4,

          // Shadows
          boxShadow: '0 4px 24px rgba(0,0,0,0.4)',
          boxShadowSecondary: '0 0 20px rgba(0,212,255,0.12)',

          // Sizing
          controlHeight: 36,
          controlHeightLG: 42,
          controlHeightSM: 28,

          // Motion
          motionDurationFast: '0.15s',
          motionDurationMid: '0.25s',
          motionDurationSlow: '0.4s',
        },
        components: {
          Table: {
            headerBg: 'rgba(0,212,255,0.05)',
            headerColor: '#8899bb',
            rowHoverBg: 'rgba(0,212,255,0.04)',
            borderColor: 'rgba(255,255,255,0.06)',
          },
          Card: {
            colorBgContainer: '#111e35',
            headerBg: 'transparent',
          },
          Menu: {
            darkItemBg: 'transparent',
            darkItemSelectedBg: 'rgba(0,212,255,0.12)',
            darkItemHoverBg: 'rgba(0,212,255,0.06)',
            darkItemColor: '#8899bb',
            darkItemSelectedColor: '#00d4ff',
          },
          Button: {
            colorBorder: 'rgba(0,212,255,0.3)',
          },
          Input: {
            colorBgContainer: '#0a1220',
          },
          Select: {
            colorBgContainer: '#0a1220',
          },
          DatePicker: {
            colorBgContainer: '#0a1220',
          },
          Dropdown: {
            colorBgElevated: '#0f1a2e',
            colorText: '#e8edf8',
          },
          Popover: {
            colorBgElevated: '#0f1a2e',
          },
          Tooltip: {
            colorBgSpotlight: '#1a2947',
          },
          Message: {
            contentBg: '#0f1a2e',
            colorText: '#e8edf8',
          },
          Modal: {
            contentBg: '#0f1a2e',
            headerBg: '#0f1a2e',
          },
          Tabs: {
            inkBarColor: '#00d4ff',
            itemSelectedColor: '#00d4ff',
          },
          Tag: {
            defaultBg: 'rgba(0,212,255,0.1)',
            defaultColor: '#00d4ff',
          },
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pools" element={<PoolList />} />
            <Route path="/stocks/:tsCode" element={<StockDetail />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/plans" element={<PlanList />} />
            <Route path="/plans/:id" element={<PlanRedirect />} />
            <Route path="/strategy" element={<StrategyPage />} />
            <Route path="/buy-radar" element={<BuyRadarPage />} />
            <Route path="/data" element={<DataPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
