import React from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { message as antdMessage } from 'antd';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  ClipboardList,
  Github,
  Loader2,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { useSubmitRepoReadmeCheckMutation } from '../../query/hooks/repo-analysis';
import RepoAnalysisCard from './RepoAnalysisCard';
import styles from './RepoCheckPage.module.css';

type RecentRepoRun = {
  runId: string;
  owner: string;
  repo: string;
  repoUrl: string;
  projectName: string;
  likelyProjectType: string;
  hypeRisk: string;
  stars: number;
  timestamp: number;
};

const RepoCheckPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation();
  const { isAuthenticated, setShowAuthModal } = useAuth();

  const [repoUrl, setRepoUrl] = React.useState('');
  const [runId, setRunId] = React.useState<string | null>(null);
  const [recentRuns, setRecentRuns] = React.useState<RecentRepoRun[]>([]);

  const submitMutation = useSubmitRepoReadmeCheckMutation();
  const queryRunId = searchParams.get('run_id');

  // Translation labels matching cards
  const typeLabel: Record<string, string> = {
    demo_wrapper: t('repo_check.type_demo_wrapper', 'Demo 包装'),
    framework_assembly: t('repo_check.type_framework_assembly', '框架组合'),
    research_prototype: t('repo_check.type_research_prototype', '研究原型'),
    product_candidate: t('repo_check.type_product_candidate', '产品候选'),
    unclear: t('repo_check.type_unclear', '暂不明确'),
  };

  const riskLabel: Record<string, string> = {
    low: t('repo_check.risk_low', '低'),
    medium: t('repo_check.risk_medium', '中'),
    high: t('repo_check.risk_high', '高'),
    unknown: t('repo_check.risk_unknown', '未知'),
  };

  // Synchronize URL query parameter with runId state
  React.useEffect(() => {
    if (queryRunId) {
      setRunId(queryRunId);
    } else {
      setRunId(null);
    }
  }, [queryRunId]);

  // Load history list from localStorage on mount and when runId changes
  React.useEffect(() => {
    const key = 'DEWFLOW_RECENT_REPO_RUNS';
    try {
      const stored = localStorage.getItem(key);
      if (stored) {
        setRecentRuns(JSON.parse(stored) as RecentRepoRun[]);
      }
    } catch {
      setRecentRuns([]);
    }
  }, [runId]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!isAuthenticated) {
      setShowAuthModal(true);
      return;
    }
    if (!repoUrl.trim()) {
      antdMessage.warning(t('repo_check.enter_url_warning', '请输入 GitHub 仓库 URL'));
      return;
    }
    try {
      const response = await submitMutation.mutateAsync(repoUrl.trim());
      setSearchParams({ run_id: response.run_id });
      setRepoUrl('');
    } catch {
      antdMessage.error(t('repo_check.submit_failed', '仓库分析任务创建失败，请稍后重试'));
    }
  };

  const handleClearHistory = () => {
    const key = 'DEWFLOW_RECENT_REPO_RUNS';
    localStorage.removeItem(key);
    setRecentRuns([]);
    antdMessage.success(t('repo_check.history_cleared', '最近分析记录已清空'));
  };

  return (
    <div className={styles.page}>
      <div className={styles.shell}>
        <button
          className={styles.backButton}
          onClick={() => {
            if (queryRunId) {
              setSearchParams({});
            } else {
              navigate('/');
            }
          }}
        >
          <ArrowLeft size={16} />
          {queryRunId ? t('repo_check.back_to_submit', '返回输入页') : t('credits.back_home', '返回主页')}
        </button>

        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <div className={styles.eyebrow}>
              <ShieldCheck size={16} />
              README Credibility Check
            </div>
            <h1>{t('repo_check.page_title', 'AI 项目可信度初筛')}</h1>
            <p>{t('repo_check.page_desc', '输入公开 GitHub 仓库，生成一份基于 README 和元信息的非技术判断报告。')}</p>
          </div>
          <form className={styles.inputBar} onSubmit={handleSubmit}>
            <Github size={20} />
            <input
              value={repoUrl}
              onChange={(event) => setRepoUrl(event.target.value)}
              placeholder="https://github.com/owner/repo"
              aria-label="GitHub repository URL"
            />
            <button type="submit" disabled={submitMutation.isPending}>
              {submitMutation.isPending ? <Loader2 size={18} /> : <ClipboardList size={18} />}
              {t('repo_check.btn_analyze', 'Analyze')}
            </button>
          </form>
        </section>

        {runId ? (
          <RepoAnalysisCard runId={runId} />
        ) : (
          <section className={styles.recentSection}>
            <div className={styles.recentHeader}>
              <h3>{t('repo_check.recent_audits', '最近分析的仓库')}</h3>
              {recentRuns.length > 0 && (
                <button className={styles.clearHistoryBtn} onClick={handleClearHistory}>
                  <Trash2 size={14} />
                  {t('repo_check.clear_history', '清空历史')}
                </button>
              )}
            </div>

            {recentRuns.length > 0 ? (
              <div className={styles.recentGrid}>
                {recentRuns.map((item) => {
                  const typeText = typeLabel[item.likelyProjectType] || item.likelyProjectType;
                  const riskText = riskLabel[item.hypeRisk] || item.hypeRisk;
                  const dateStr = new Date(item.timestamp).toLocaleDateString();

                  return (
                    <div
                      key={item.runId}
                      className={styles.recentCard}
                      onClick={() => setSearchParams({ run_id: item.runId })}
                    >
                      <div className={styles.cardTop}>
                        <h4>{item.projectName}</h4>
                        <span>⭐ {item.stars}</span>
                      </div>
                      <div className={styles.cardMeta}>
                        <span>{t('repo_check.meta_project_type', '项目类型')}: {typeText}</span>
                        <span className={styles[item.hypeRisk]}>
                          {t('repo_check.metric_hype_risk', '夸大风险')}: {riskText}
                        </span>
                      </div>
                      <div className={styles.cardFooter}>
                        <span>{item.owner}/{item.repo}</span>
                        <span>{dateStr}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className={styles.emptyHistory}>
                <ClipboardList size={32} className={styles.emptyIcon} />
                <span>{t('repo_check.empty_history', '暂无最近分析记录。输入上方 GitHub 链接，开启您的第一次可信度评估吧！')}</span>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  );
};

export default RepoCheckPage;
