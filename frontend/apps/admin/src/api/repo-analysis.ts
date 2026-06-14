import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import {
  repoAnalysisRunResponseSchema,
  repoAnalysisSubmitResponseSchema,
  type RepoAnalysisRunResponse,
  type RepoAnalysisSubmitResponse,
} from '../schemas/repo-analysis';
import { API_URLS } from './urls';

export const submitRepoReadmeCheckAPI = (
  repoUrl: string,
): Promise<RepoAnalysisSubmitResponse> => {
  return request
    .post<unknown, unknown>(API_URLS.REPO_ANALYSIS.README_CHECK, {
      repo_url: repoUrl,
    })
    .then((response) =>
      parseWithSchema(
        repoAnalysisSubmitResponseSchema,
        response,
        '仓库分析提交响应格式无效',
      ),
    );
};

export const getRepoAnalysisRunAPI = (
  runId: string,
): Promise<RepoAnalysisRunResponse> => {
  return request
    .get<unknown, unknown>(API_URLS.REPO_ANALYSIS.RUN(runId))
    .then((response) =>
      parseWithSchema(
        repoAnalysisRunResponseSchema,
        response,
        '仓库分析结果响应格式无效',
      ),
    );
};
