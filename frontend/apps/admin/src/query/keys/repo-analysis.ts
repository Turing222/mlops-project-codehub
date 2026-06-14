export const repoAnalysisKeys = {
  all: () => ['repo-analysis'] as const,
  run: (runId: string) => [...repoAnalysisKeys.all(), 'run', runId] as const,
};
