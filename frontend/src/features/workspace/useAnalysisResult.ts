import { useQuery } from '@tanstack/react-query'
import { ApiError, getAnalysisResult } from '../../api/client'
import type { AnalysisResult } from '../../api/types'

export type ResultLoader = (analysisId: string) => Promise<AnalysisResult>

export function useAnalysisResult(
  analysisId: string,
  loadResult: ResultLoader = getAnalysisResult,
) {
  return useQuery({
    queryKey: ['analysis-result', analysisId],
    queryFn: async () => {
      const result = await loadResult(analysisId)
      if (result.analysis_id !== analysisId) {
        throw new ApiError(0, 'invalid_server_response')
      }
      return result
    },
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
  })
}
