export const creditKeys = {
  all: () => ['credits'] as const,
  me: () => [...creditKeys.all(), 'me'] as const,
  transactions: (params: { source?: string; skip?: number; limit?: number }) =>
    [...creditKeys.all(), 'transactions', params] as const,
};
