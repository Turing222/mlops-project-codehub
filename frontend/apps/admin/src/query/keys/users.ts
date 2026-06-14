export const userKeys = {
  all: () => ['users'] as const,
  query: (params: { username?: string; email?: string }) =>
    [...userKeys.all(), 'query', params] as const,
};
