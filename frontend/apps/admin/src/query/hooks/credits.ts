import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getMyCreditsAPI, dailyCheckinAPI, listMyTransactionsAPI } from '../../api/credits';
import { creditKeys } from '../keys/credits';
import { useAuth } from '../../context/useAuth';

export function useMyCreditsQuery() {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: creditKeys.me(),
    queryFn: getMyCreditsAPI,
    enabled: isAuthenticated,
    staleTime: 1000 * 60 * 5, // Cache for 5 minutes
  });
}

export function useCreditTransactionsQuery(params: { source?: string; skip?: number; limit?: number }) {
  const { isAuthenticated } = useAuth();
  return useQuery({
    queryKey: creditKeys.transactions(params),
    queryFn: () => listMyTransactionsAPI(params),
    enabled: isAuthenticated,
  });
}

export function useDailyCheckinMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: dailyCheckinAPI,
    retry: false, // Prevent duplicate check-in retries
    onSuccess: () => {
      // Invalidate current balance and recent transactions immediately
      queryClient.invalidateQueries({ queryKey: creditKeys.me() });
      queryClient.invalidateQueries({ queryKey: creditKeys.all() });
    },
  });
}
