import { useQuery } from '@tanstack/react-query';

import { getAuthConfigAPI } from '../../api/auth';
import { authKeys } from '../keys/auth';

export function useSystemAuthConfig() {
  return useQuery({
    queryKey: authKeys.systemConfig(),
    queryFn: getAuthConfigAPI,
    staleTime: 1000 * 60 * 5,
  });
}

export function usePasswordLoginEnabled(): boolean {
  const { data } = useSystemAuthConfig();
  return data?.['enable-password-login'] === true;
}
