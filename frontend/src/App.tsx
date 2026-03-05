import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/Dashboard'
import PoolList from './pages/Pools/PoolList'
import Alerts from './pages/Alerts'
import PlanList from './pages/Plans/PlanList'
import PlanDetail from './pages/Plans/PlanDetail'
import StockDetail from './pages/Stocks/StockDetail'
import StrategyPage from './pages/Strategy/StrategyPage'
import DataPage from './pages/Data/DataPage'

function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pools" element={<PoolList />} />
            <Route path="/stocks/:tsCode" element={<StockDetail />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/plans" element={<PlanList />} />
            <Route path="/plans/:id" element={<PlanDetail />} />
            <Route path="/strategy" element={<StrategyPage />} />
            <Route path="/data" element={<DataPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
