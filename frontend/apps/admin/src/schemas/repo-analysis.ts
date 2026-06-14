import * as z from 'zod';

export const repoAnalysisStatusSchema = z.enum(['pending', 'running', 'succeeded', 'failed']);

export const repoAnalysisSubmitResponseSchema = z.object({
  run_id: z.string(),
  task_id: z.string(),
  status: repoAnalysisStatusSchema,
});

export const evidenceItemSchema = z.object({
  id: z.string(),
  kind: z.string(),
  title: z.string(),
  detail: z.string(),
  source: z.string(),
});

export const repoEvidenceBundleSchema = z.object({
  readme_excerpt: z.string(),
  readme_claims: z.array(evidenceItemSchema),
  metadata_signals: z.array(evidenceItemSchema),
  missing_signals: z.array(evidenceItemSchema),
});

export const claimedCapabilitySchema = z.object({
  claim: z.string(),
  evidence_text: z.string().nullable().optional(),
  confidence: z.enum(['low', 'medium', 'high']),
});

export const credibilityFindingSchema = z.object({
  title: z.string(),
  severity: z.enum(['positive', 'neutral', 'warning', 'risk']),
  non_technical_explanation: z.string(),
  evidence_refs: z.array(z.string()),
});

export const readmeCredibilityAssessmentSchema = z.object({
  project_name: z.string(),
  one_sentence_summary: z.string(),
  likely_project_type: z.enum([
    'demo_wrapper',
    'framework_assembly',
    'research_prototype',
    'product_candidate',
    'unclear',
  ]),
  non_technical_verdict: z.string(),
  hype_risk: z.enum(['low', 'medium', 'high', 'unknown']),
  evidence_strength: z.enum(['weak', 'moderate', 'strong', 'unknown']),
  claimed_capabilities: z.array(claimedCapabilitySchema),
  credibility_signals: z.array(z.string()),
  missing_signals: z.array(z.string()),
  recommended_next_questions: z.array(z.string()),
  findings: z.array(credibilityFindingSchema),
  caveat: z.string(),
});

export const repoAnalysisRunSchema = z.object({
  id: z.string(),
  status: repoAnalysisStatusSchema,
  repo_url: z.string(),
  owner: z.string(),
  repo: z.string(),
  task_id: z.string().nullable().optional(),
  rubric_version: z.string(),
  error_message: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const repoSubjectSchema = z.object({
  provider: z.literal('github'),
  owner: z.string(),
  repo: z.string(),
  url: z.string(),
});

export const repoSnapshotSchema = z.object({
  default_branch: z.string(),
  readme_sha: z.string(),
  stars: z.number().int(),
  forks: z.number().int(),
  topics: z.array(z.string()),
  license: z.string().nullable().optional(),
  repo_updated_at: z.string().nullable().optional(),
  fetched_at: z.string(),
});

export const repoReportSchema = z.object({
  structured: readmeCredibilityAssessmentSchema,
  markdown: z.string(),
  generated_by: z.enum(['pydantic_ai', 'fallback']),
});

export const repoAnalysisRunResponseSchema = z.object({
  run: repoAnalysisRunSchema,
  subject: repoSubjectSchema.nullable().optional(),
  snapshot: repoSnapshotSchema.nullable().optional(),
  evidence: repoEvidenceBundleSchema.nullable().optional(),
  report: repoReportSchema.nullable().optional(),
});

export type RepoAnalysisStatus = z.infer<typeof repoAnalysisStatusSchema>;
export type RepoAnalysisSubmitResponse = z.infer<typeof repoAnalysisSubmitResponseSchema>;
export type RepoAnalysisRunResponse = z.infer<typeof repoAnalysisRunResponseSchema>;
export type EvidenceItem = z.infer<typeof evidenceItemSchema>;
export type CredibilityFinding = z.infer<typeof credibilityFindingSchema>;
