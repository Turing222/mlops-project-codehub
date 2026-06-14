import { describe, expect, it } from 'vitest';
import {
  repoAnalysisRunResponseSchema,
  repoAnalysisSubmitResponseSchema,
} from './repo-analysis';

describe('repo analysis schemas', () => {
  it('parses submit response', () => {
    const result = repoAnalysisSubmitResponseSchema.parse({
      run_id: 'run-1',
      task_id: 'task-1',
      status: 'pending',
    });

    expect(result.status).toBe('pending');
  });

  it('parses completed run response', () => {
    const result = repoAnalysisRunResponseSchema.parse({
      run: {
        id: 'run-1',
        status: 'succeeded',
        repo_url: 'https://github.com/openai/codex',
        owner: 'openai',
        repo: 'codex',
        task_id: 'task-1',
        rubric_version: 'readme-only-v1',
        error_message: null,
        created_at: '2026-05-27T00:00:00Z',
        updated_at: '2026-05-27T00:00:00Z',
      },
      subject: {
        provider: 'github',
        owner: 'openai',
        repo: 'codex',
        url: 'https://github.com/openai/codex',
      },
      snapshot: {
        default_branch: 'main',
        readme_sha: 'abc',
        stars: 1,
        forks: 0,
        topics: ['ai'],
        license: 'MIT',
        repo_updated_at: '2026-05-27T00:00:00Z',
        fetched_at: '2026-05-27T00:00:00Z',
      },
      evidence: {
        readme_excerpt: 'README',
        readme_claims: [],
        metadata_signals: [],
        missing_signals: [],
      },
      report: {
        generated_by: 'fallback',
        markdown: '# Report',
        structured: {
          project_name: 'codex',
          one_sentence_summary: 'summary',
          likely_project_type: 'unclear',
          non_technical_verdict: 'verdict',
          hype_risk: 'unknown',
          evidence_strength: 'weak',
          claimed_capabilities: [],
          credibility_signals: [],
          missing_signals: [],
          recommended_next_questions: [],
          findings: [],
          caveat: 'README-only',
        },
      },
    });

    expect(result.report?.structured.project_name).toBe('codex');
  });
});
