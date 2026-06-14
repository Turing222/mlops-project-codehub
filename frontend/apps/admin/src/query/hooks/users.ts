import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { queryUserAPI, updateUserAPI, registerUserAPI, uploadUsersCSVAPI } from '../../api/users';
import { userKeys } from '../keys/users';
import type { UserRegistrationPayload, UserUpdatePayload } from '../../types/user';
import { mutationRetry } from '../../lib/http/mutation-policy';
import { createIdempotencyKey } from '../../lib/http/idempotency';

export function useUserSearchQuery(params: { username?: string; email?: string }) {
  const hasParams = Boolean(params.username || params.email);
  return useQuery({
    queryKey: userKeys.query(params),
    queryFn: () => queryUserAPI(params),
    enabled: hasParams,
  });
}

export function useUpdateUserMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string | number; data: UserUpdatePayload }) =>
      updateUserAPI(id, data),
    retry: false,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.all() });
    },
  });
}

export function useRegisterUserMutation() {
  return useMutation({
    mutationFn: (data: UserRegistrationPayload) => registerUserAPI(data),
    retry: false,
  });
}

type UploadVariables = { file: File; idempotencyKey: string };

export function useUploadUsersCSVMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, idempotencyKey }: UploadVariables) =>
      uploadUsersCSVAPI(file, idempotencyKey),
    retry: (failureCount, error) =>
      mutationRetry(failureCount, error, 1),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.all() });
    },
  });
}

export { createIdempotencyKey };
