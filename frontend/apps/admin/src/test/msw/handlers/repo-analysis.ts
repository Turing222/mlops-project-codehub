import { http, HttpResponse } from 'msw';
import { API_URLS } from '../../../api/urls';

// Store request counts to simulate dynamic status polling (pending -> running -> succeeded)
const pollStore = new Map<string, number>();

export const repoAnalysisHandlers = [
  // 1. Submit README credibility check
  http.post(API_URLS.REPO_ANALYSIS.README_CHECK, async ({ request }) => {
    const payload = (await request.json()) as { repo_url?: string };
    
    if (!payload.repo_url) {
      return HttpResponse.json(
        { detail: 'repo_url field is required' },
        { status: 422 }
      );
    }

    const runId = crypto.randomUUID();
    const taskId = crypto.randomUUID();
    pollStore.set(runId, 0);

    return HttpResponse.json({
      run_id: runId,
      task_id: taskId,
      status: 'pending',
    }, { status: 202 });
  }),

  // 2. Fetch repo analysis runs status (polls dynamically)
  http.get(API_URLS.REPO_ANALYSIS.RUN(':id'), async ({ params }) => {
    const runId = params.id as string;
    const currentPollCount = pollStore.get(runId) ?? 0;
    
    // Simulate progression: 0: pending, 1: running, >=2: succeeded
    let status: 'pending' | 'running' | 'succeeded' = 'pending';
    if (currentPollCount === 1) {
      status = 'running';
    } else if (currentPollCount >= 2) {
      status = 'succeeded';
    }

    // Increment poll count for next query
    pollStore.set(runId, currentPollCount + 1);

    if (status === 'pending' || status === 'running') {
      return HttpResponse.json({
        run: {
          id: runId,
          status,
          repo_url: 'https://github.com/mock-owner/mock-repo',
          owner: 'mock-owner',
          repo: 'mock-repo',
          task_id: crypto.randomUUID(),
          rubric_version: 'readme-only-v1',
          error_message: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        subject: null,
        snapshot: null,
        evidence: null,
        report: null,
      });
    }

    // Succeeded response: Full detailed mock credibility analysis
    return HttpResponse.json({
      run: {
        id: runId,
        status: 'succeeded',
        repo_url: 'https://github.com/mock-owner/mock-repo',
        owner: 'mock-owner',
        repo: 'mock-repo',
        task_id: crypto.randomUUID(),
        rubric_version: 'readme-only-v1',
        error_message: null,
        created_at: new Date(Date.now() - 5000).toISOString(),
        updated_at: new Date().toISOString(),
      },
      subject: {
        provider: 'github',
        owner: 'mock-owner',
        repo: 'mock-repo',
        url: 'https://github.com/mock-owner/mock-repo',
      },
      snapshot: {
        default_branch: 'main',
        readme_sha: 'mock-readme-sha-hash-12345',
        stars: 3500,
        forks: 480,
        topics: ['artificial-intelligence', 'agent', 'automation'],
        license: 'Apache-2.0',
        repo_updated_at: '2026-05-27T08:00:00Z',
        fetched_at: new Date().toISOString(),
      },
      evidence: {
        readme_excerpt: '### Mock Project\nThis is a mock repository exhibiting robust credentials...',
        readme_claims: [
          {
            id: 'c1',
            kind: 'readme_claim',
            title: '10x Performance Increase',
            detail: 'The README claims that the compile pipeline runs 10x faster than standard setups.',
            source: 'README.md#L45',
          },
        ],
        metadata_signals: [
          {
            id: 'm1',
            kind: 'metadata_signal',
            title: 'Active Community Adoption',
            detail: 'Over 3,500 GitHub Stars and steady growth in forks indicates authentic interest.',
            source: 'GitHub API Metadata',
          },
        ],
        missing_signals: [
          {
            id: 'ms1',
            kind: 'missing_signal',
            title: 'No CI Testing Badges',
            detail: 'The project is missing continuous integration build status badges in the main header.',
            source: 'README.md',
          },
        ],
      },
      report: {
        structured: {
          project_name: 'Mock Intelligent Agent',
          one_sentence_summary: 'An autonomous agent framework written in TypeScript.',
          likely_project_type: 'product_candidate',
          non_technical_verdict: 'This project displays highly authentic engagement and standard modular packaging, although continuous testing status should be verified independently.',
          hype_risk: 'low',
          evidence_strength: 'strong',
          claimed_capabilities: [
            {
              claim: '10x Performance Increase',
              evidence_text: 'The README compiles standard workflows in less than 200ms compared to 2000ms historically.',
              confidence: 'medium',
            },
          ],
          credibility_signals: [
            'Licensed under Apache-2.0',
            'Strong community engagement (3.5k stars)',
            'Comprehensive installation guides',
          ],
          missing_signals: ['No CI integration badges in README header'],
          recommended_next_questions: [
            'Is there an active automated test suite running in GitHub Actions?',
            'What production use-cases have been documented by the team?',
          ],
          findings: [
            {
              title: 'High Star Validation',
              severity: 'positive',
              non_technical_explanation: 'Over 3.5k stars show substantial organic adoption and validation by the community.',
              evidence_refs: ['m1'],
            },
            {
              title: 'Missing Build Status Badge',
              severity: 'warning',
              non_technical_explanation: 'The absence of a CI build status badge suggests automated test verification might be missing or manual.',
              evidence_refs: ['ms1'],
            },
          ],
          caveat: 'This audit is based solely on repository README and metadata. No code review has been performed.',
        },
        markdown: '# Mock Repo analysis Report\n\n- Likely Project Type: Product Candidate\n- Stars: 3500\n- Hype Risk: Low\n\nThis is a highly credible repository with clear documentation...',
        generated_by: 'pydantic_ai',
      },
    });
  }),
];
