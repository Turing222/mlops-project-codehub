import { useMutation, useQuery } from '@tanstack/react-query';
import {
  getRepoAnalysisRunAPI,
  submitRepoReadmeCheckAPI,
} from '../../api/repo-analysis';
import { repoAnalysisKeys } from '../keys/repo-analysis';

export function useSubmitRepoReadmeCheckMutation() {
  return useMutation({
    mutationFn: submitRepoReadmeCheckAPI,
    retry: false,
  });
}

export function useRepoAnalysisRunQuery(runId: string | null) {
  return useQuery({
    queryKey: runId ? repoAnalysisKeys.run(runId) : repoAnalysisKeys.all(),
    queryFn: () => getRepoAnalysisRunAPI(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === 'pending' || status === 'running' ? 2000 : false;
    },
  });
}
