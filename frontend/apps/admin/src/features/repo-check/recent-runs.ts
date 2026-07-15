import * as z from 'zod';

const STORAGE_KEY = 'DEWFLOW_RECENT_REPO_RUNS';
const MAX_RECENT_RUNS = 10;

export const recentRepoRunSchema = z.object({
  runId: z.string().min(1),
  owner: z.string(),
  repo: z.string(),
  repoUrl: z.string().min(1),
  projectName: z.string(),
  likelyProjectType: z.string(),
  hypeRisk: z.string(),
  stars: z.number(),
  timestamp: z.number(),
});

export type RecentRepoRun = z.infer<typeof recentRepoRunSchema>;

const recentRepoRunListSchema = z.array(recentRepoRunSchema);

export function listRecentRepoRuns(): RecentRepoRun[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return [];
    const parsed: unknown = JSON.parse(stored);
    const result = recentRepoRunListSchema.safeParse(parsed);
    return result.success ? result.data : [];
  } catch {
    // Do not delete the raw value on read failure — avoid silent data loss.
    return [];
  }
}

export function upsertRecentRepoRun(run: RecentRepoRun): RecentRepoRun[] {
  const validated = recentRepoRunSchema.safeParse(run);
  if (!validated.success) {
    return listRecentRepoRuns();
  }

  const next = listRecentRepoRuns()
    .filter((item) => item.runId !== validated.data.runId && item.repoUrl !== validated.data.repoUrl);
  next.unshift(validated.data);
  const capped = next.slice(0, MAX_RECENT_RUNS);

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(capped));
  } catch {
    // Best-effort write; still return the canonical in-memory list.
  }
  return capped;
}

export function clearRecentRepoRuns(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage failures must not throw into UI handlers.
  }
}
