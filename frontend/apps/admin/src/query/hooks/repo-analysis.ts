import { useMutation, useQuery } from '@tanstack/react-query';
import {
  getRepoAnalysisRunAPI,
  submitRepoReadmeCheckAPI,
} from '../../api/repo-analysis';
import { repoAnalysisKeys } from '../keys/repo-analysis';
import { useAuthStore } from '../../stores/auth-store';
import { useMeQuery } from './auth';

export function useSubmitRepoReadmeCheckMutation() {
  return useMutation({
    mutationFn: submitRepoReadmeCheckAPI,
    retry: false,
  });
}

export function useRepoAnalysisRunQuery(runId: string | null) {
  const token = useAuthStore((s) => s.token);
  const { data: user } = useMeQuery();
  return useQuery({
    queryKey: runId ? repoAnalysisKeys.run(runId) : repoAnalysisKeys.all(),
    queryFn: () => getRepoAnalysisRunAPI(runId!),
    enabled: !!token && !!user && Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === 'pending' || status === 'running' ? 2000 : false;
    },
  });
}
