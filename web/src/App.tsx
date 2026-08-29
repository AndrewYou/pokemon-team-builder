import { Route, Routes } from 'react-router-dom'

import BuilderPage from '@/pages/BuilderPage'
import HealthPage from '@/pages/HealthPage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<BuilderPage />} />
      <Route path="/health" element={<HealthPage />} />
    </Routes>
  )
}
