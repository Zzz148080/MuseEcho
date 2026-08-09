import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { AnalysisPage } from './pages/AnalysisPage'
import './styles/global.css'

function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <AnalysisPage />
    </QueryClientProvider>
  )
}

export default App
