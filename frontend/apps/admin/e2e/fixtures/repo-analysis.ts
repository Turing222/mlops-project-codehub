import type { Page } from '@playwright/test';

const FIXED_RUN_ID = 'e2e-run-mock-001';

type MockRepoAnalysisOptions = {
  runId?: string;
  projectName?: string;
  repoUrl?: string;
};

export function buildSucceededRepoAnalysisRun(
  runId: string,
  options: MockRepoAnalysisOptions = {},
) {
  const repoUrl = options.repoUrl ?? 'https://github.com/mock-owner/mock-repo';
  const projectName = options.projectName ?? 'Mock Intelligent Agent';

  return {
    run: {
      id: runId,
      status: 'succeeded',
      repo_url: repoUrl,
      owner: 'mock-owner',
      repo: 'mock-repo',
      task_id: 'task-mock-001',
      rubric_version: 'readme-only-v1',
      error_message: null,
      created_at: new Date(Date.now() - 5000).toISOString(),
      updated_at: new Date().toISOString(),
    },
    subject: {
      provider: 'github',
      owner: 'mock-owner',
      repo: 'mock-repo',
      url: repoUrl,
    },
    snapshot: {
      default_branch: 'main',
      readme_sha: 'mock-readme-sha',
      stars: 128,
      forks: 12,
      topics: ['ai', 'workflow'],
      license: 'MIT',
      repo_updated_at: '2026-05-27T08:00:00Z',
      fetched_at: new Date().toISOString(),
    },
    evidence: {
      readme_excerpt: 'A mock repository used by Playwright e2e.',
      readme_claims: [],
      metadata_signals: [],
      missing_signals: [],
    },
    report: {
      structured: {
        project_name: projectName,
        one_sentence_summary: 'A credible open-source workflow project.',
        likely_project_type: 'product_candidate',
        non_technical_verdict: 'Documentation and metadata look consistent for a real product repo.',
        hype_risk: 'low',
        evidence_strength: 'strong',
        claimed_capabilities: [],
        credibility_signals: ['Clear README structure'],
        missing_signals: [],
        recommended_next_questions: ['Are production deployments documented?'],
        findings: [
          {
            title: 'Readable README',
            severity: 'positive',
            non_technical_explanation: 'The README explains the project purpose in plain language.',
            evidence_refs: [],
          },
        ],
        caveat: 'README-only assessment.',
      },
      markdown: '# Mock Repo Report\n\nHappy path e2e fixture.',
      generated_by: 'fallback',
    },
  };
}

/**
 * Mocks submit + polling for repo analysis. Poll progression:
 * pending -> running -> succeeded.
 */
export async function mockRepoAnalysisRoutes(
  page: Page,
  options: MockRepoAnalysisOptions = {},
) {
  const runId = options.runId ?? FIXED_RUN_ID;
  const pollCounts = new Map<string, number>();

  await page.route('**/api/v1/repo-analysis/readme-check', async (route) => {
    pollCounts.set(runId, 0);
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: runId,
        task_id: 'task-mock-001',
        status: 'pending',
      }),
    });
  });

  await page.route('**/api/v1/repo-analysis/runs/**', async (route) => {
    const url = route.request().url();
    const resolvedRunId = url.split('/').pop()?.split('?')[0] ?? runId;
    const current = pollCounts.get(resolvedRunId) ?? 0;
    pollCounts.set(resolvedRunId, current + 1);

    if (current < 1) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run: {
            id: resolvedRunId,
            status: 'pending',
            repo_url: options.repoUrl ?? 'https://github.com/mock-owner/mock-repo',
            owner: 'mock-owner',
            repo: 'mock-repo',
            task_id: 'task-mock-001',
            rubric_version: 'readme-only-v1',
            error_message: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
          subject: null,
          snapshot: null,
          evidence: null,
          report: null,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildSucceededRepoAnalysisRun(resolvedRunId, options)),
    });
  });
}

export { FIXED_RUN_ID as MOCK_REPO_ANALYSIS_RUN_ID };
