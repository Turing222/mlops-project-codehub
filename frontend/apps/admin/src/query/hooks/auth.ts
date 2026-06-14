import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUserProfileAPI, updateUserProfileAPI } from '../../api/auth';
import { authKeys } from '../keys/auth';
import { useAuthStore } from '../../stores/auth-store';

export function useMeQuery() {
  const token = useAuthStore((s) => s.token);
  return useQuery({
    queryKey: authKeys.me(),
    queryFn: getUserProfileAPI,
    enabled: !!token && token !== 'null' && token !== 'undefined' && token !== '',
    staleTime: 1000 * 60 * 5,
  });
}

export function useUpdateProfileMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateUserProfileAPI,
    onSuccess: (data) => {
      queryClient.setQueryData(authKeys.me(), data);
      queryClient.invalidateQueries({ queryKey: authKeys.all() });
    },
  });
}
