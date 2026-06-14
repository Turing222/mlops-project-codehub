export const chatKeys = {
  all: () => ['chat'] as const,
  sessions: () => [...chatKeys.all(), 'sessions'] as const,
  sessionDetail: (sessionId: string) =>
    [...chatKeys.all(), 'session', sessionId] as const,
};
