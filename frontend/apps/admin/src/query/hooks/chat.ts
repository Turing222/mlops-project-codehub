import { useQuery } from '@tanstack/react-query';
import { getSessionsAPI, getSessionDetailAPI } from '../../api/chat';
import { chatKeys } from '../keys/chat';
import { useAuthStore } from '../../stores/auth-store';
import { useMeQuery } from './auth';

export function useChatSessionsQuery(skip = 0, limit = 50) {
  const token = useAuthStore((s) => s.token);
  const { data: user } = useMeQuery();
  return useQuery({
    queryKey: chatKeys.sessions(),
    queryFn: () => getSessionsAPI(skip, limit),
    enabled: !!token && !!user,
  });
}

export function useSessionDetailQuery(
  sessionId: string | null,
  skip = 0,
  limit = 100,
) {
  const token = useAuthStore((s) => s.token);
  const { data: user } = useMeQuery();
  return useQuery({
    queryKey: chatKeys.sessionDetail(sessionId!),
    queryFn: () => getSessionDetailAPI(sessionId!, skip, limit),
    enabled: !!token && !!user && !!sessionId,
  });
}
