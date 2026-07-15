import { useQuery, useMutation, useQueryClient, queryOptions } from '@tanstack/react-query';
import { getUserProfileAPI, updateUserProfileAPI } from '../../api/auth';
import { authKeys } from '../keys/auth';
import { useAuthStore } from '../../stores/auth-store';

/** Shared /users/me options for useMeQuery and AuthProvider.login bootstrap. */
export function meQueryOptions() {
  return queryOptions({
    queryKey: authKeys.me(),
    queryFn: getUserProfileAPI,
    staleTime: 1000 * 60 * 5,
  });
}

function isUsableToken(token: string | null | undefined): token is string {
  return !!token && token !== 'null' && token !== 'undefined' && token !== '';
}

export function useMeQuery() {
  const token = useAuthStore((s) => s.token);
  return useQuery({
    ...meQueryOptions(),
    enabled: isUsableToken(token),
  });
}

export function useUpdateProfileMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateUserProfileAPI,
    onMutate: () => ({
      tokenAtStart: useAuthStore.getState().token,
    }),
    onSuccess: (data, _variables, context) => {
      // A delayed A profile success must not overwrite B's /me after identity replace.
      const currentToken = useAuthStore.getState().token;
      if (!context?.tokenAtStart || context.tokenAtStart !== currentToken) {
        return;
      }
      queryClient.setQueryData(authKeys.me(), data);
      queryClient.invalidateQueries({ queryKey: authKeys.all() });
    },
  });
}
