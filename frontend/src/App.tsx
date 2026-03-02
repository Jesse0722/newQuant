import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/Dashboard'
import PoolList from './pages/Pools/PoolList'
import PoolDetail from './pages/Pools/PoolDetail'
import Alerts from './pages/Alerts'
import PlanList from './pages/Plans/PlanList'
import PlanDetail from './pages/Plans/PlanDetail'

function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/pools" element={<PoolList />} />
            <Route path="/pools/:id" element={<PoolDetail />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/plans" element={<PlanList />} />
            <Route path="/plans/:id" element={<PlanDetail />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}

export default App
