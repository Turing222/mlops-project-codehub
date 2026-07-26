export const authKeys = {
  all: () => ['auth'] as const,
  me: () => [...authKeys.all(), 'me'] as const,
  systemConfig: () => [...authKeys.all(), 'system-config'] as const,
};
