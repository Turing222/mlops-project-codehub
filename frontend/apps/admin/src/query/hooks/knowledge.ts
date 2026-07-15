import { useMutation, useQuery, useQueryClient, queryOptions } from '@tanstack/react-query';
import {
  deleteKBFileAPI,
  getDefaultKBAPI,
  getDefaultKBFilesAPI,
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
