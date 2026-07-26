export const knowledgeKeys = {
  all: () => ['knowledge'] as const,
  default: () => [...knowledgeKeys.all(), 'default'] as const,
  files: () => [...knowledgeKeys.all(), 'files'] as const,
  task: (taskId: string) => [...knowledgeKeys.all(), 'task', taskId] as const,
};
