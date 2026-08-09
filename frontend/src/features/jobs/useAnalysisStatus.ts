import { useQuery } from '@tanstack/react-query'
import { getAnalysisStatus } from '../../api/client'
import type { AnalysisStage, AnalysisStatus } from '../../api/types'

const TERMINAL_STAGES = new Set<AnalysisStage>([
  'complete',
  'failed',
  'deleted',
  'expired',
])

export type StatusLoader = (analysisId: string) => Promise<AnalysisStatus>

export function useAnalysisStatus(
  analysisId: string,
  loadStatus: StatusLoader = getAnalysisStatus,
) {
  return useQuery({
    queryKey: ['analysis-status', analysisId],
    queryFn: () => loadStatus(analysisId),
    refetchInterval: (query) =>
      statusPollInterval(query.state.data, Boolean(query.state.error)),
    refetchIntervalInBackground: false,
    refetchOnReconnect: (query) =>
      statusPollInterval(query.state.data, Boolean(query.state.error)) !== false,
    refetchOnWindowFocus: (query) =>
      statusPollInterval(query.state.data, Boolean(query.state.error)) !== false,
    retry: false,
  })
}

export function statusPollInterval(
  status: AnalysisStatus | undefined,
  hasError = false,
): number | false {
  return hasError || (status && TERMINAL_STAGES.has(status.stage)) ? false : 1500
}
