import { useMutation, useQuery, useQueryClient, queryOptions } from '@tanstack/react-query';
import {
  deleteKBFileAPI,
  getDefaultKBAPI,
  getDefaultKBFilesAPI,
  getKBTaskStatusAPI,
  uploadKBFileAPI,
} from '../../api/knowledge';
import { useAuthStore } from '../../stores/auth-store';
import { knowledgeKeys } from '../keys/knowledge';
import { useMeQuery } from './auth';

/** Shared options for observer + imperative first resolve (enabled:false still allows fetchQuery). */
export function defaultKBQueryOptions() {
  return queryOptions({
    queryKey: knowledgeKeys.default(),
    queryFn: getDefaultKBAPI,
    staleTime: Infinity,
  });
}

function useKnowledgeAuthEnabled(enabled: boolean): boolean {
  const token = useAuthStore((s) => s.token);
  const { data: user } = useMeQuery();
  return !!token && !!user && enabled;
}

export function useDefaultKBQuery({ enabled }: { enabled: boolean }) {
  return useQuery({
    ...defaultKBQueryOptions(),
    enabled: useKnowledgeAuthEnabled(enabled),
  });
}

export function useKBFilesQuery({ enabled }: { enabled: boolean }) {
  return useQuery({
    queryKey: knowledgeKeys.files(),
    queryFn: getDefaultKBFilesAPI,
    enabled: useKnowledgeAuthEnabled(enabled),
    staleTime: 0,
  });
}

export function useDeleteKBFileMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fileId: string) => deleteKBFileAPI(fileId),
    retry: false,
    onMutate: () => ({
      tokenAtStart: useAuthStore.getState().token,
    }),
    onSuccess: (_data, _fileId, context) => {
      const currentToken = useAuthStore.getState().token;
      if (!context?.tokenAtStart || context.tokenAtStart !== currentToken) {
        return;
      }
      void queryClient.invalidateQueries({ queryKey: knowledgeKeys.files() });
    },
  });
}

export function useUploadKBFileMutation() {
  return useMutation({
    mutationFn: (file: File) => uploadKBFileAPI(file),
    retry: false,
  });
}

export function useKBTaskStatusQuery(
  taskId: string | null | undefined,
  { enabled }: { enabled: boolean },
) {
  const normalizedTaskId = taskId?.trim() ?? '';
  const canQuery = enabled && normalizedTaskId.length > 0;

  return useQuery({
    queryKey: knowledgeKeys.task(normalizedTaskId),
    queryFn: () => getKBTaskStatusAPI(normalizedTaskId),
    enabled: useKnowledgeAuthEnabled(canQuery),
    retry: false,
    refetchInterval: (query) => {
      const status = query.state.data?.status?.toLowerCase();
      if (status === 'completed' || status === 'failed') {
        return false;
      }
      return 1000;
    },
  });
}
