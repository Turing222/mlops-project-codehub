import React, { useState, useEffect, useMemo } from 'react';
import { Spin, message as antdMessage } from 'antd';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileJson,
  Github,
  Loader2,
  Copy,
} from 'lucide-react';
import { useRepoAnalysisRunQuery } from '../../query/hooks/repo-analysis';
import type { EvidenceItem, RepoAnalysisStatus } from '../../schemas/repo-analysis';
import styles from './RepoCheckPage.module.css';

interface RepoAnalysisCardProps {
  runId: string;
}

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

// Reusable Markdown Renderer Component
const MarkdownRenderer: React.FC<{ text: string; renderBadge: (ref: string) => React.ReactNode }> = ({ text, renderBadge }) => {
  const lines = text.split('\n');

  const parseLineText = (lineText: string) => {
    // 1. Split by backticks to find inline code blocks
    const codeParts = lineText.split('`');
    
    return codeParts.flatMap((codePart, codeIdx) => {
      const isCode = codeIdx % 2 === 1;
      
      if (isCode) {
        // Render custom styled badges for specific code values
        const val = codePart.trim().toLowerCase();
        const badgeStyle = {
          padding: '2px 6px',
          borderRadius: '4px',
          fontSize: '12px',
          fontWeight: '600' as const,
          fontFamily: 'monospace',
          display: 'inline-flex',
          alignItems: 'center',
          gap: '4px',
          margin: '0 2px',
          verticalAlign: 'middle',
        };
        
        let customClass = '';
        const label = codePart;
        let icon = '';

        if (val === 'low' || val === 'weak') {
          icon = '🟢';
          customClass = styles.badgeLow || '';
        } else if (val === 'medium' || val === 'moderate') {
          icon = '🟡';
          customClass = styles.badgeMedium || '';
        } else if (val === 'high' || val === 'strong' || val === 'risk') {
          icon = '🔴';
          customClass = styles.badgeHigh || '';
        } else if (val === 'positive') {
          icon = '🟢';
          customClass = styles.badgePositive || '';
        } else if (val === 'neutral') {
          icon = '⚪';
          customClass = styles.badgeNeutral || '';
        } else if (val === 'warning') {
          icon = '🟡';
          customClass = styles.badgeWarning || '';
        } else {
          // Standard generic inline code block
          return (
            <code key={codeIdx} style={{
              background: 'var(--color-bg-subtle, #f1f5f9)',
              color: 'var(--color-text-main, #0f172a)',
              padding: '2px 4px',
              borderRadius: '4px',
              fontSize: '13px',
              fontFamily: 'monospace',
              border: '1px solid var(--color-border)',
            }}>
              {codePart}
            </code>
          );
        }

        return (
          <span key={codeIdx} className={`${styles.inlineValBadge} ${customClass}`} style={badgeStyle}>
            {icon && <span>{icon}</span>}
            <span>{label}</span>
          </span>
        );
      }

      // 2. Outside backticks: split by bold '**'
      const boldParts = codePart.split('**');
      return boldParts.flatMap((boldPart, boldIdx) => {
        const isBold = boldIdx % 2 === 1;
        
        // 3. Split by evidence badges
        const badgeRegex = /\[(readme_claim_\d+|missing_signal_\d+|metadata_[a-z0-9_]+)\]/g;
        const subParts = boldPart.split(badgeRegex);
        
        const elements = subParts.map((subPart, subIdx) => {
          const isBadge = subIdx % 2 === 1;
          if (isBadge) {
            return (
              <span key={`${boldIdx}-${subIdx}`} style={{ margin: '0 4px', display: 'inline-flex', verticalAlign: 'middle' }}>
                {renderBadge(subPart)}
              </span>
            );
          }
          return subPart;
        });

        if (isBold) {
          return <strong key={boldIdx}>{elements}</strong>;
        }
        return elements;
      });
    });
  };

  const encodeMermaid = (code: string) => {
    try {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark' || 
                     document.body.classList.contains('dark') || 
                     document.body.getAttribute('data-theme') === 'dark';
      const json = {
        code: code,
        mermaid: {
          theme: isDark ? 'dark' : 'default',
          background: isDark ? '#1e293b' : '#ffffff'
        }
      };
      const str = JSON.stringify(json);
      const base64 = btoa(unescape(encodeURIComponent(str)));
      return `https://mermaid.ink/svg/${base64}`;
    } catch {
      return '';
    }
  };

  const parsedBlocks: React.ReactNode[] = [];
  let inMermaidBlock = false;
  let mermaidCodeLines: string[] = [];
  
  let inGenericCodeBlock = false;
  let genericCodeLines: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Check for mermaid block boundaries
    if (trimmed.startsWith('```mermaid')) {
      inMermaidBlock = true;
      mermaidCodeLines = [];
      continue;
    }

    if (inMermaidBlock) {
      if (trimmed.startsWith('```')) {
        inMermaidBlock = false;
        const code = mermaidCodeLines.join('\n');
        const imgUrl = encodeMermaid(code);
        if (imgUrl) {
          parsedBlocks.push(
            <div key={`mermaid-${i}`} style={{ display: 'flex', justifyContent: 'center', margin: '20px 0', padding: '16px', background: 'var(--color-bg-subtle, #f8fafc)', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
              <img src={imgUrl} alt="Mermaid Diagram" style={{ maxWidth: '100%', height: 'auto' }} />
            </div>
          );
        } else {
          parsedBlocks.push(
            <pre key={`err-${i}`} style={{ background: '#0f172a', color: '#e2e8f0', padding: '12px', borderRadius: '6px', fontSize: '13px' }}>{code}</pre>
          );
        }
        continue;
      }
      mermaidCodeLines.push(line);
      continue;
    }

    // Check for generic code block boundaries
    if (trimmed.startsWith('```')) {
      if (inGenericCodeBlock) {
        inGenericCodeBlock = false;
        const code = genericCodeLines.join('\n');
        parsedBlocks.push(
          <pre key={`code-${i}`} style={{ background: '#0f172a', color: '#e2e8f0', padding: '16px', borderRadius: '8px', overflow: 'auto', fontSize: '13px', margin: '12px 0' }}>
            <code>{code}</code>
          </pre>
        );
      } else {
        inGenericCodeBlock = true;
        genericCodeLines = [];
      }
      continue;
    }

    if (inGenericCodeBlock) {
      genericCodeLines.push(line);
      continue;
    }

    // Standard markdown rendering
    if (!trimmed) {
      parsedBlocks.push(<div key={i} style={{ height: '8px' }} />);
      continue;
    }

    if (trimmed.startsWith('# ')) {
      parsedBlocks.push(<h1 key={i} className={styles.mdH1}>{parseLineText(trimmed.slice(2))}</h1>);
      continue;
    }
    if (trimmed.startsWith('## ')) {
      parsedBlocks.push(<h2 key={i} className={styles.mdH2}>{parseLineText(trimmed.slice(3))}</h2>);
      continue;
    }
    if (trimmed.startsWith('### ')) {
      parsedBlocks.push(<h3 key={i} className={styles.mdH3}>{parseLineText(trimmed.slice(4))}</h3>);
      continue;
    }
    if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
      parsedBlocks.push(<li key={i} className={styles.mdLi}>{parseLineText(trimmed.slice(2))}</li>);
      continue;
    }

    parsedBlocks.push(<p key={i} className={styles.mdP}>{parseLineText(trimmed)}</p>);
  }

  return (
    <div className={styles.mdContainer}>
      {parsedBlocks}
    </div>
  );
};

const RepoAnalysisCard: React.FC<RepoAnalysisCardProps> = ({ runId }) => {
  const { t } = useTranslation();
  const [showEvidenceJson, setShowEvidenceJson] = useState(false);
  const [timerTick, setTimerTick] = useState(() => Date.now());
  
  const runQuery = useRepoAnalysisRunQuery(runId);
  const runData = runQuery.data;
  const report = runData?.report;
  const assessment = report?.structured;

  const currentStatus = runData?.run.status ?? 'pending';

  useEffect(() => {
    if (currentStatus !== 'pending' && currentStatus !== 'running') {
      return;
    }
    const timer = setInterval(() => {
      setTimerTick(Date.now());
    }, 100);

    return () => clearInterval(timer);
  }, [currentStatus]);

  // Save successful run to history list in localStorage
  useEffect(() => {
    if (runData && runData.run.status === 'succeeded') {
      const structuredReport = runData.report?.structured;
      if (structuredReport) {
        try {
          const key = 'DEWFLOW_RECENT_REPO_RUNS';
          const existingStr = localStorage.getItem(key);
          let list = existingStr ? (JSON.parse(existingStr) as RecentRepoRun[]) : [];
          
          // Remove duplicates
          list = list.filter((item) => item.runId !== runData.run.id && item.repoUrl !== runData.run.repo_url);
          
          const newRecord = {
            runId: runData.run.id,
            owner: runData.run.owner,
            repo: runData.run.repo,
            repoUrl: runData.run.repo_url,
            projectName: structuredReport.project_name || runData.run.repo,
            likelyProjectType: structuredReport.likely_project_type || 'unclear',
            hypeRisk: structuredReport.hype_risk || 'unknown',
            stars: runData.snapshot?.stars || 0,
            timestamp: Date.now(),
          };
          
          list.unshift(newRecord);
          list = list.slice(0, 10); // cap at 10 items
          localStorage.setItem(key, JSON.stringify(list));
        } catch {
          return;
        }
      }
    }
  }, [runData]);

  const elapsed = useMemo(() => {
    if (!runData || (currentStatus !== 'pending' && currentStatus !== 'running')) {
      return 0;
    }
    const createdAtTime = new Date(runData.run.created_at).getTime();
    return Math.max(0, (timerTick - createdAtTime) / 1000);
  }, [currentStatus, runData, timerTick]);

  const durationSec = (() => {
    if (!runData) return null;
    const start = new Date(runData.run.created_at).getTime();
    const end = new Date(runData.run.updated_at).getTime();
    const diff = (end - start) / 1000;
    return diff > 0 ? diff.toFixed(1) : '0.1';
  })();

  const computedDurations = useMemo(() => {
    if (!runData) return null;
    const createdAtTime = new Date(runData.run.created_at).getTime();
    const updatedAtTime = new Date(runData.run.updated_at).getTime();
    const status = runData.run.status;

    const submitSec = 0.1;
    const succeededSec = 0.2;

    if (status === 'succeeded' || status === 'failed') {
      const totalSec = Math.max(0.5, (updatedAtTime - createdAtTime) / 1000);
      const pendingSec = Math.min(1.2, Math.max(0.1, totalSec * 0.05));
      const runningSec = Math.max(0.1, totalSec - submitSec - pendingSec - (status === 'succeeded' ? succeededSec : 0.1));
      
      return {
        submit: submitSec.toFixed(1) + 's',
        pending: pendingSec.toFixed(1) + 's',
        running: runningSec.toFixed(1) + 's',
        succeeded: status === 'succeeded' ? succeededSec.toFixed(1) + 's' : '',
      };
    }

    let pendingSec = Math.max(0.1, elapsed - submitSec);
    if (status === 'pending') {
      pendingSec = Math.max(0.1, elapsed - submitSec);
    } else if (status === 'running') {
      pendingSec = Math.min(1.2, Math.max(0.1, elapsed * 0.05));
    }

    let runningSec = 0;
    if (status === 'running') {
      runningSec = Math.max(0.1, elapsed - submitSec - pendingSec);
    }

    return {
      submit: submitSec.toFixed(1) + 's',
      pending: status === 'pending' ? '' : pendingSec.toFixed(1) + 's',
      running: status === 'running' ? '' : (runningSec > 0 ? runningSec.toFixed(1) + 's' : ''),
      succeeded: '',
    };
  }, [elapsed, runData]);

  const steps: Array<{ id: RepoAnalysisStatus | 'submit'; label: string }> = [
    { id: 'submit', label: t('repo_check.step_submit', '提交任务') },
    { id: 'pending', label: t('repo_check.step_pending', '等待调度') },
    { id: 'running', label: t('repo_check.step_running', '分析 README') },
    { id: 'succeeded', label: t('repo_check.step_succeeded', '生成报告') },
  ];

  const statusLabel: Record<RepoAnalysisStatus, string> = {
    pending: t('repo_check.status_pending', '等待调度'),
    running: t('repo_check.status_running', '分析中'),
    succeeded: t('repo_check.status_succeeded', '已完成'),
    failed: t('repo_check.status_failed', '失败'),
  };

  const riskLabel: Record<string, string> = {
    low: t('repo_check.risk_low', '低'),
    medium: t('repo_check.risk_medium', '中'),
    high: t('repo_check.risk_high', '高'),
    unknown: t('repo_check.risk_unknown', '未知'),
  };

  const typeLabel: Record<string, string> = {
    demo_wrapper: t('repo_check.type_demo_wrapper', 'Demo 包装'),
    framework_assembly: t('repo_check.type_framework_assembly', '框架组合'),
    research_prototype: t('repo_check.type_research_prototype', '研究原型'),
    product_candidate: t('repo_check.type_product_candidate', '产品候选'),
    unclear: t('repo_check.type_unclear', '暂不明确'),
  };

  const evidenceItems = useMemo(() => {
    const evidence = runData?.evidence;
    if (!evidence) return new Map<string, EvidenceItem>();
    return new Map(
      [
        ...evidence.readme_claims,
        ...evidence.metadata_signals,
        ...evidence.missing_signals,
      ].map((item) => [item.id, item]),
    );
  }, [runData?.evidence]);

  const downloadMarkdown = () => {
    if (!report?.markdown) return;
    const blob = new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${assessment?.project_name || 'repo-report'}-readme-check.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const severityLabels: Record<string, string> = {
    positive: '🟢 ' + t('repo_check.severity_positive', '积极因素'),
    neutral: '⚪ ' + t('repo_check.severity_neutral', '客观中立'),
    warning: '🟡 ' + t('repo_check.severity_warning', '潜在疑点'),
    risk: '🔴 ' + t('repo_check.severity_risk', '虚假风险'),
  };

  const renderEvidenceRefBadge = (ref: string) => {
    if (ref.startsWith('readme_claim_')) {
      const num = ref.replace('readme_claim_', '');
      return (
        <span className={`${styles.evidenceBadge} ${styles.badgeClaim}`}>
          ✨ {t('repo_check.badge_claim', '宣称能力')} {num}
        </span>
      );
    }
    if (ref.startsWith('missing_signal_')) {
      const num = ref.replace('missing_signal_', '');
      return (
        <span className={`${styles.evidenceBadge} ${styles.badgeMissing}`}>
          ⚠️ {t('repo_check.badge_missing', '缺失信号')} {num}
        </span>
      );
    }
    if (ref.startsWith('metadata_')) {
      const type = ref.replace('metadata_', '');
      let label = type;
      let icon = '📊';
      if (type === 'stars') { label = t('repo_check.meta_stars', 'Stars'); icon = '⭐'; }
      else if (type === 'forks') { label = t('repo_check.meta_forks', 'Forks'); icon = '🍴'; }
      else if (type === 'license') { label = t('repo_check.meta_license', '开源协议'); icon = '📜'; }
      else if (type === 'topics') { label = t('repo_check.meta_topics', '项目主题'); icon = '🏷️'; }
      return (
        <span className={`${styles.evidenceBadge} ${styles.badgeMeta}`}>
          {icon} {label}
        </span>
      );
    }
    return <code>{ref}</code>;
  };

  const handleCopyRichText = async () => {
    if (!assessment) return;

    try {
      const title = `AI 项目可信度初筛报告 - ${assessment.project_name}`;
      const typeText = typeLabel[assessment.likely_project_type] || assessment.likely_project_type;
      const riskText = riskLabel[assessment.hype_risk] || assessment.hype_risk;
      const genMethod = report?.generated_by || '-';

      let findingsHtml = '';
      assessment.findings.forEach((f) => {
        const sevText = severityLabels[f.severity] || f.severity;
        let refListHtml = '';
        f.evidence_refs.forEach((ref) => {
          const item = evidenceItems.get(ref);
          let label = ref;
          if (ref.startsWith('readme_claim_')) {
            label = `✨ 宣称能力 ${ref.replace('readme_claim_', '')}`;
          } else if (ref.startsWith('missing_signal_')) {
            label = `⚠️ 缺失信号 ${ref.replace('missing_signal_', '')}`;
          } else if (ref.startsWith('metadata_')) {
            const m = ref.replace('metadata_', '');
            if (m === 'stars') label = '⭐ Stars 数量';
            else if (m === 'forks') label = '🍴 Forks 数量';
            else if (m === 'license') label = '📜 开源协议';
            else if (m === 'topics') label = '🏷️ 项目主题';
          }
          refListHtml += `<li style="margin: 4px 0; color: #475569; font-size: 13px;"><b>[${label}]</b> ${item?.detail || ''}</li>`;
        });

        findingsHtml += `
          <div style="margin-bottom: 16px; padding: 12px; border: 1px solid #e2e8f0; border-radius: 6px; background-color: #f8fafc;">
            <h4 style="margin: 0 0 8px 0; font-size: 14px; color: #0f172a;">${f.title} <span style="font-size: 12px; font-weight: normal; margin-left: 8px;">(${sevText})</span></h4>
            <p style="margin: 0 0 8px 0; font-size: 13px; color: #334155; line-height: 1.5;">${f.non_technical_explanation}</p>
            ${refListHtml ? `<ul style="margin: 0; padding-left: 20px;">${refListHtml}</ul>` : ''}
          </div>
        `;
      });

      const html = `
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 680px; padding: 20px; color: #1e293b;">
          <h2 style="margin: 0 0 12px 0; font-size: 20px; color: #0f172a; border-bottom: 2px solid #3b82f6; padding-bottom: 6px;">${title}</h2>
          
          <div style="margin-bottom: 16px; line-height: 1.6;">
            <p style="margin: 0 0 8px 0; font-weight: bold; font-size: 15px; color: #1e293b;">📌 ${t('repo_check.verdict', '评估结论')}：${assessment.one_sentence_summary}</p>
            <p style="margin: 0; font-size: 14px; color: #475569; background-color: #f1f5f9; padding: 12px; border-radius: 6px; border-left: 4px solid #94a3b8;">${assessment.non_technical_verdict}</p>
          </div>

          <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 13px;">
            <thead>
              <tr style="background-color: #f1f5f9; text-align: left;">
                <th style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">${t('repo_check.metric_project_type', '项目类型')}</th>
                <th style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">${t('repo_check.metric_hype_risk', '夸大风险')}</th>
                <th style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">${t('repo_check.metric_evidence_strength', '证据强度')}</th>
                <th style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">${t('repo_check.metric_generation_method', '生成方式')}</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">${typeText}</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">${riskText}</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">${assessment.evidence_strength}</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">${genMethod}</td>
              </tr>
            </tbody>
          </table>

          <h3 style="margin: 0 0 12px 0; font-size: 16px; color: #0f172a; border-bottom: 1px solid #cbd5e1; padding-bottom: 4px;">🔍 ${t('repo_check.title_critical_findings', '关键发现')}</h3>
          <div>${findingsHtml}</div>
          
          <p style="margin: 20px 0 0 0; font-size: 11px; color: #94a3b8; text-align: center;">${assessment.caveat}</p>
        </div>
      `;

      const text = `${title}\n\n` +
        `📌 ${t('repo_check.verdict', '评估结论')}：${assessment.one_sentence_summary}\n\n` +
        `${assessment.non_technical_verdict}\n\n` +
        `【评估指标】\n` +
        `- 项目类型: ${typeText}\n` +
        `- 夸大风险: ${riskText}\n` +
        `- 证据强度: ${assessment.evidence_strength}\n` +
        `- 生成方式: ${genMethod}\n\n` +
        `🔍 ${t('repo_check.title_critical_findings', '关键发现')}\n` +
        assessment.findings.map((f, i) => {
          const sevText = severityLabels[f.severity] || f.severity;
          const refLines = f.evidence_refs.map(ref => {
            const item = evidenceItems.get(ref);
            return `  [${ref}] ${item?.detail || ''}`;
          }).join('\n');
          return `${i+1}. ${f.title} (${sevText})\n   ${f.non_technical_explanation}\n${refLines}`;
        }).join('\n\n') +
        `\n\n${assessment.caveat}`;

      const blobHtml = new Blob([html], { type: 'text/html' });
      const blobText = new Blob([text], { type: 'text/plain' });
      const item = new ClipboardItem({
        'text/html': blobHtml,
        'text/plain': blobText,
      });

      await navigator.clipboard.write([item]);
      antdMessage.success(t('repo_check.copy_success', '已复制富文本报告，可直接粘贴至飞书、Notion或邮件！'));
    } catch {
      antdMessage.error(t('repo_check.copy_failed', '复制失败，请重试'));
    }
  };

  return (
    <div className={styles.cardContainer}>
      <section className={styles.timeline} style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', gap: '10px', flex: '1', minWidth: '280px' }}>
          {steps.map((step, index) => {
            const state = stepState(step.id, currentStatus);
            
            // Calculate step-by-step elapsed time when done
            let stepDuration = '';
            if (state === 'done' && computedDurations) {
              stepDuration = computedDurations[step.id as keyof typeof computedDurations] || '';
            }

            return (
              <div key={step.id} className={`${styles.step} ${styles[state]}`} style={{ flex: 1, justifyContent: 'center', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <div className={styles.stepIcon}>
                  {state === 'done' ? (
                    <CheckCircle2 size={16} />
                  ) : index === 0 ? (
                    <Github size={16} />
                  ) : (
                    <Loader2 size={16} />
                  )}
                </div>
                <span>{step.label}</span>
                {stepDuration && (
                  <span style={{ fontSize: '10.5px', opacity: 0.6, fontWeight: 500, fontFamily: 'monospace' }}>
                    ({stepDuration})
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Live Timer Badge when task is active */}
        {(currentStatus === 'pending' || currentStatus === 'running') && (
          <div className={styles.durationTag}>
            <Loader2 size={12} style={{ animation: 'spin 1.2s linear infinite', marginRight: '6px' }} />
            {t('repo_check.elapsed_time', '已耗时')}: {elapsed.toFixed(1)}s
          </div>
        )}

        {/* Final Execution Duration Badge on success */}
        {currentStatus === 'succeeded' && durationSec && (
          <div className={styles.durationTag}>
            {t('repo_check.total_time', '总耗时')}: {durationSec}s
          </div>
        )}
      </section>

      {runQuery.isLoading && (
        <div className={styles.loadingPanel} style={{ marginTop: '12px' }}>
          <Spin />
          <span>{t('repo_check.syncing_status', '正在同步分析状态')}</span>
        </div>
      )}

      {runData?.run.status === 'failed' && (
        <div className={styles.errorPanel} style={{ marginTop: '12px' }}>
          <AlertCircle size={20} />
          <span>{runData.run.error_message || t('repo_check.failed_message', '仓库分析失败，请稍后重试')}</span>
        </div>
      )}

      {assessment && runData?.subject && (
        <div className={styles.reportGrid} style={{ marginTop: '20px' }}>
          <div className={styles.verdictPanel}>
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.kicker}>{t('repo_check.verdict', '评估结论')}</span>
                <h2>{assessment.project_name}</h2>
              </div>
              <span className={`${styles.statusBadge} ${styles[runData.run.status]}`}>
                {statusLabel[runData.run.status]}
              </span>
            </div>
            <p className={styles.summary}>{assessment.one_sentence_summary}</p>
            <p className={styles.verdict}>{assessment.non_technical_verdict}</p>
            <div className={styles.metrics}>
              <Metric label={t('repo_check.metric_project_type', '项目类型')} value={typeLabel[assessment.likely_project_type] || assessment.likely_project_type} />
              <Metric label={t('repo_check.metric_hype_risk', '夸大风险')} value={riskLabel[assessment.hype_risk] || assessment.hype_risk} />
              <Metric label={t('repo_check.metric_evidence_strength', '证据强度')} value={assessment.evidence_strength} />
              <Metric label={t('repo_check.metric_generation_method', '生成方式')} value={report?.generated_by || '-'} />
            </div>
            <div className={styles.actions}>
              <button onClick={downloadMarkdown}>
                <Download size={16} />
                {t('repo_check.action_markdown', 'Markdown')}
              </button>
              <button onClick={handleCopyRichText}>
                <Copy size={16} />
                {t('repo_check.action_copy_report', '复制富文本报告')}
              </button>
              <button onClick={() => setShowEvidenceJson((value) => !value)}>
                <FileJson size={16} />
                {t('repo_check.action_evidence_json', 'Evidence JSON')}
              </button>
            </div>
          </div>

          <div className={styles.sidePanel}>
            <h3>{t('repo_check.title_credibility_signals', '可信信号')}</h3>
            <SignalList items={assessment.credibility_signals} emptyText={t('repo_check.empty_text', '暂无')} />
            <h3>{t('repo_check.title_missing_signals', '缺失信号')}</h3>
            <SignalList items={assessment.missing_signals} emptyText={t('repo_check.empty_text', '暂无')} />
          </div>

          <div className={styles.findingsPanel}>
            <h3>{t('repo_check.title_critical_findings', '关键发现')}</h3>
            <div className={styles.findingsList}>
              {assessment.findings.map((finding) => (
                <details key={finding.title} className={styles.finding}>
                  <summary>
                    <span>{finding.title}</span>
                    <b className={styles[finding.severity]}>{severityLabels[finding.severity] || finding.severity}</b>
                  </summary>
                  <p>{finding.non_technical_explanation}</p>
                  <div className={styles.evidenceRefs}>
                    {finding.evidence_refs.map((ref) => {
                      const item = evidenceItems.get(ref);
                      return (
                        <div key={ref} className={styles.evidenceRef}>
                          <div style={{ display: 'flex', alignItems: 'center' }}>
                            {renderEvidenceRefBadge(ref)}
                          </div>
                          <span>{item?.detail || t('repo_check.evidence_detail_not_found', '未找到证据详情')}</span>
                        </div>
                      );
                    })}
                  </div>
                </details>
              ))}
            </div>
          </div>

          <div className={styles.markdownPanel}>
            <h3>{t('repo_check.title_markdown_report', 'Markdown 报告')}</h3>
            <MarkdownRenderer text={report?.markdown || ''} renderBadge={renderEvidenceRefBadge} />
          </div>

          {showEvidenceJson && (
            <div className={styles.jsonPanel}>
              <h3>Evidence JSON</h3>
              <pre>{JSON.stringify(runData.evidence, null, 2)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.metric}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function SignalList({ items, emptyText }: { items: string[]; emptyText: string }) {
  if (!items.length) return <p className={styles.emptyText}>{emptyText}</p>;
  return (
    <ul className={styles.signalList}>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function stepState(
  step: RepoAnalysisStatus | 'submit',
  status: RepoAnalysisStatus | null,
): 'idle' | 'running' | 'done' | 'error' {
  if (!status) return step === 'submit' ? 'running' : 'idle';
  if (status === 'failed') return step === 'succeeded' ? 'error' : 'done';
  const order = ['submit', 'pending', 'running', 'succeeded'];
  const currentIndex = order.indexOf(status);
  const stepIndex = order.indexOf(step);
  if (stepIndex < currentIndex) return 'done';
  if (stepIndex === currentIndex) return status === 'succeeded' ? 'done' : 'running';
  return 'idle';
}

export default RepoAnalysisCard;
