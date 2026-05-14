import React from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { isAuthenticated } from './session'

const ProtectedRoute: React.FC = () => {
  const location = useLocation()
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return <Outlet />
}

export default ProtectedRoute
