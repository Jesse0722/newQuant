import { Navigate, useParams } from 'react-router-dom'

const PlanRedirect: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  return <Navigate to={id ? `/plans?expand=${id}` : '/plans'} replace />
}

export default PlanRedirect
