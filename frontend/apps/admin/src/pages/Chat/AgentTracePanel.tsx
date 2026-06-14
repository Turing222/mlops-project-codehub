import React, { useState } from 'react';
import { Check, Loader, AlertCircle, Minus, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Activity, Globe, Database, ExternalLink } from 'lucide-react';
import { Button, Tooltip } from 'antd';
import { useTranslation } from 'react-i18next';
import type { AgentTraceStep, CitationItem } from '../../types/agent-trace';
import styles from './AgentTracePanel.module.css';

interface AgentTracePanelProps {
    traceSteps: AgentTraceStep[];
    citations: CitationItem[];
    ingestionSteps?: AgentTraceStep[];
    activeTraceTab?: 'rag' | 'ingestion';
    setActiveTraceTab?: (tab: 'rag' | 'ingestion') => void;
    collapsed?: boolean;
    onToggle?: () => void;
}

const AgentTracePanel: React.FC<AgentTracePanelProps> = ({
    traceSteps,
    citations,
    ingestionSteps = [],
    activeTraceTab = 'rag',
    setActiveTraceTab,
    collapsed = false,
    onToggle,
}) => {
    const [citationsExpanded, setCitationsExpanded] = useState(false);
    const [expandedCitations, setExpandedCitations] = useState<Record<string, boolean>>({});
    const { t } = useTranslation();

    const toggleCitationExpand = (chunkId: string) => {
        setExpandedCitations(prev => ({
            ...prev,
            [chunkId]: !prev[chunkId],
        }));
    };

    const ingestionStepNames: Record<string, string> = {
        'file-upload': t('trace.ingestion.file-upload'),
        'content-audit': t('trace.ingestion.content-audit'),
        'semantic-chunk': t('trace.ingestion.semantic-chunk'),
        'vector-index': t('trace.ingestion.vector-index'),
        'ingestion-complete': t('trace.ingestion.ingestion-complete'),
    };

    const currentSteps = activeTraceTab === 'ingestion' ? ingestionSteps : traceSteps;
    const hasTrace = currentSteps.length > 0;
    const summaryMetrics = activeTraceTab === 'rag' ? getSummaryMetrics(traceSteps) : [];

    if (collapsed) {
        return (
            <div className={`${styles['trace-panel']} ${styles['collapsed-trace-panel']}`} data-testid="trace-panel-collapsed">
                <Tooltip title={t('trace.expand')} placement="left">
                    <Button
                        className={styles['toggle-btn']}
                        type="text"
                        icon={<ChevronLeft size={18} />}
                        aria-label={t('trace.expand')}
                        onClick={onToggle}
                        data-testid="trace-panel-expand-btn"
                    />
                </Tooltip>
                <div className={styles['collapsed-icon-btn']}>
                    <Activity size={20} className={styles['spin-slow']} style={{ animationDuration: '3s' }} />
                </div>
                <div className={styles['collapsed-vertical-title']}>
                    {t('trace.title')}
                </div>
            </div>
        );
    }

    return (
        <div className={styles['trace-panel']}>
            <div className={styles['trace-panel-header']}>
                {onToggle && (
                    <Tooltip title={t('trace.collapse')} placement="left">
                        <Button
                            className={styles['toggle-btn']}
                            type="text"
                            icon={<ChevronRight size={18} />}
                            aria-label={t('trace.collapse')}
                            onClick={onToggle}
                            data-testid="trace-panel-collapse-btn"
                        />
                    </Tooltip>
                )}
                <div className={styles['trace-tabs']}>
                    <button
                        className={`${styles['trace-tab-btn']} ${activeTraceTab === 'rag' ? styles['active'] : ''}`}
                        onClick={() => setActiveTraceTab?.('rag')}
                    >
                        {t('trace.tab_rag')}
                    </button>
                    <button
                        className={`${styles['trace-tab-btn']} ${activeTraceTab === 'ingestion' ? styles['active'] : ''}`}
                        onClick={() => setActiveTraceTab?.('ingestion')}
                    >
                        {t('trace.tab_ingestion')}
                    </button>
                </div>
            </div>

            <div className={styles['trace-panel-body']}>
                {!hasTrace ? (
                    <div className={styles['trace-panel-empty']} data-testid="trace-panel-empty">
                        {t('trace.empty_hint')}
                    </div>
                ) : (
                    <>
                        {summaryMetrics.length > 0 && (
                            <div className={styles['trace-metrics-summary']} data-testid="trace-metrics-summary">
                                {summaryMetrics.map((item) => (
                                    <div key={item.key} className={styles['trace-metric-item']}>
                                        <span className={styles['trace-metric-label']}>{t(`trace.summary.${item.key}`)}</span>
                                        <span className={styles['trace-metric-value']}>{item.value}</span>
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className={styles['trace-timeline']}>
                            {currentSteps.map((step, index) => (
                                <div
                                    key={step.id}
                                    className={`${styles['trace-step']} ${styles[`trace-step-${step.status}`]}`}
                                    data-testid={`trace-step-${step.id}`}
                                    style={{
                                        animationDelay: `${index * 60}ms`,
                                    }}
                                >
                                    <div
                                        className={
                                            styles['trace-step-indicator']
                                        }
                                    >
                                        <div
                                            className={styles['trace-step-dot']}
                                        />
                                        {index < currentSteps.length - 1 && (
                                            <div
                                                className={
                                                    styles['trace-step-line']
                                                }
                                            />
                                        )}
                                    </div>
                                    <div
                                        className={styles['trace-step-content']}
                                    >
                                        <div
                                            className={
                                                styles['trace-step-title']
                                            }
                                        >
                                            {activeTraceTab === 'ingestion'
                                                ? ingestionStepNames[step.id] || step.id
                                                : t(`trace.steps.${step.id}`)}
                                        </div>
                                        {step.description && (
                                            <div
                                                className={
                                                    styles['trace-step-desc']
                                                }
                                            >
                                                {step.description}
                                            </div>
                                        )}
                                        {step.metricDetails && (() => {
                                            const displayMetrics = Object.fromEntries(
                                                Object.entries(step.metricDetails).filter(([k]) => k !== 'route_reason'),
                                            );
                                            return Object.keys(displayMetrics).length > 0 ? (
                                                <div className={styles['trace-step-details']}>
                                                    {Object.entries(displayMetrics).map(([key, value]) => (
                                                        <span key={key}>
                                                            {t(`trace.metrics.${key}`, key)}: {formatMetricValue(key, value)}
                                                        </span>
                                                    ))}
                                                </div>
                                            ) : null;
                                        })()}
                                        {step.metricDetails?.route_reason && (
                                            <div className={styles['trace-step-reason-box']}>
                                                <div className={styles['trace-step-reason-header']}>
                                                    <div style={{ display: 'flex', alignItems: 'center', width: '100%', justifyContent: 'space-between' }}>
                                                        <span>💡 {t('trace.route_reason_title', 'RAG 决策路由分析')}</span>
                                                        {step.metricDetails?.route_confidence !== undefined && (
                                                            <span className={styles['trace-confidence-badge']}>
                                                                {t('trace.confidence_label', '置信度')}: {(Number(step.metricDetails.route_confidence) * 100).toFixed(0)}%
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className={styles['trace-step-reason-content']}>
                                                    {String(step.metricDetails.route_reason)}
                                                    {step.metricDetails?.planner_refusal === true && (
                                                        <div style={{ display: 'block', width: '100%' }}>
                                                            <div className={styles['trace-refusal-alert']}>
                                                                ⚠️ {t('trace.preflight_refused', '规划器前置决策：拒答此问题')}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    {step.durationMs !== undefined && (
                                        <div className={styles['trace-step-duration']} data-testid={`trace-step-duration-${step.id}`}>
                                            {formatDuration(step.durationMs)}
                                        </div>
                                    )}
                                    <div className={styles['trace-step-icon']}>
                                        {step.status === 'done' && (
                                            <Check size={14} />
                                        )}
                                        {step.status === 'running' && (
                                            <Loader
                                                size={14}
                                                className={styles['spin']}
                                            />
                                        )}
                                        {step.status === 'error' && (
                                            <AlertCircle size={14} />
                                        )}
                                        {step.status === 'skipped' && (
                                            <Minus size={14} />
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>

                        {activeTraceTab === 'rag' && (
                            <div className={styles['trace-citations']}>
                                <div
                                    className={
                                        styles['trace-citations-header']
                                    }
                                    data-testid="trace-citations-header"
                                    onClick={() =>
                                        setCitationsExpanded(!citationsExpanded)
                                    }
                                    role="button"
                                    tabIndex={0}
                                    onKeyDown={(e) => {
                                        if (
                                            e.key === 'Enter' ||
                                            e.key === ' '
                                        ) {
                                            setCitationsExpanded(
                                                !citationsExpanded,
                                            );
                                        }
                                    }}
                                >
                                    <span>
                                        {t('trace.citations_count', {
                                            count: citations.length,
                                        })}
                                    </span>
                                    <ChevronDown
                                        size={14}
                                        className={
                                            citationsExpanded
                                                ? styles['rotated']
                                                : ''
                                        }
                                    />
                                </div>
                                {citationsExpanded && (
                                    <div
                                        className={
                                            styles['trace-citations-list']
                                        }
                                        data-testid="trace-citations-list"
                                    >
                                        {citations.length === 0 ? (
                                            <div
                                                className={
                                                    styles[
                                                        'trace-citations-empty'
                                                    ]
                                                }
                                                data-testid="trace-citations-empty"
                                            >
                                                {t('trace.no_citations')}
                                            </div>
                                        ) : (
                                             citations.map((cit) => {
                                                const webUrl = cit.url
                                                    || (cit.documentName.startsWith('http') ? cit.documentName : undefined);
                                                const isWebUrl = Boolean(webUrl);
                                                const pageLabel = (cit.metaInfo?.page_label as string | number | undefined) || (cit.metaInfo?.page as string | number | undefined);
                                                const locationText = pageLabel
                                                    ? `${t('trace.page_label', '第')} ${pageLabel} ${t('trace.page_unit', '页')}`
                                                    : (typeof cit.chunkIndex === 'number' ? `${t('trace.paragraph_label', '第')} ${cit.chunkIndex + 1} ${t('trace.paragraph_unit', '段')}` : '');
                                                const sectionPath = cit.metaInfo?.section_path as string | undefined;
                                                const isExpanded = !!expandedCitations[cit.chunkId];
                                                const needsTruncation = cit.summarySnippet.length > 150;

                                                return (
                                                    <div
                                                        key={cit.chunkId}
                                                        data-testid="citation-card"
                                                        className={styles['citation-card']}
                                                    >
                                                        <div 
                                                            className={`${styles['citation-card-header']} ${needsTruncation ? styles['clickable-header'] : ''}`}
                                                            onClick={needsTruncation ? () => toggleCitationExpand(cit.chunkId) : undefined}
                                                        >
                                                            {isWebUrl ? (
                                                                <Globe size={14} className={styles['citation-icon-web']} />
                                                            ) : (
                                                                <Database size={14} className={styles['citation-icon-db']} />
                                                            )}
                                                            <div className={styles['citation-card-name-container']}>
                                                                {isWebUrl ? (
                                                                    <a 
                                                                        href={webUrl}
                                                                        target="_blank" 
                                                                        rel="noopener noreferrer"
                                                                        className={styles['citation-web-link']}
                                                                        onClick={(e) => e.stopPropagation()}
                                                                    >
                                                                        {cit.documentName}
                                                                        <ExternalLink size={11} className={styles['citation-link-icon']} />
                                                                    </a>
                                                                ) : (
                                                                    <span className={styles['citation-card-name']}>
                                                                        {cit.documentName}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            {needsTruncation && (
                                                                <div className={styles['header-chevron-container']}>
                                                                    <ChevronDown 
                                                                        size={14} 
                                                                        className={`${styles['header-chevron']} ${isExpanded ? styles['rotated'] : ''}`} 
                                                                    />
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div className={styles['citation-card-meta']}>
                                                            {cit.chunkId && (
                                                                <span className={styles['citation-meta-badge']}>
                                                                    {cit.chunkId}
                                                                </span>
                                                            )}
                                                            {locationText && (
                                                                <span className={styles['citation-meta-location']}>
                                                                    {locationText}
                                                                </span>
                                                            )}
                                                            {((cit.scoreKind === 'bifrost_rerank' && cit.rerankScore !== undefined ? cit.rerankScore : cit.relevanceScore) > 0) && (
                                                                <span className={styles['citation-meta-score']}>
                                                                    {((cit.scoreKind === 'bifrost_rerank' && cit.rerankScore !== undefined ? cit.rerankScore : cit.relevanceScore) * 100).toFixed(0)}% {cit.scoreKind === 'bifrost_rerank' ? t('trace.rerank_score', '重排相关度') : t('trace.score', '相关度')}
                                                                </span>
                                                            )}
                                                        </div>
                                                        {sectionPath && (
                                                            <div className={styles['citation-card-section-path']} title={sectionPath}>
                                                                <span className={styles['citation-section-label']}>{t('trace.section_path_label', '📖 章节：')}</span>
                                                                <span className={styles['citation-section-value']}>{sectionPath}</span>
                                                            </div>
                                                        )}
                                                        {cit.summarySnippet && (
                                                            <div className={styles['citation-card-snippet-container']}>
                                                                <div className={styles['citation-card-snippet']}>
                                                                    {isExpanded 
                                                                        ? cit.summarySnippet 
                                                                        : (needsTruncation ? `${cit.summarySnippet.slice(0, 150)}...` : cit.summarySnippet)}
                                                                </div>
                                                                {needsTruncation && (
                                                                    <div className={styles['expand-btn-wrapper']}>
                                                                        <Button
                                                                            type="link"
                                                                            size="small"
                                                                            className={styles['citation-expand-btn']}
                                                                            icon={isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                                                                            onClick={() => toggleCitationExpand(cit.chunkId)}
                                                                        >
                                                                            {isExpanded ? t('trace.show_less', '收起段落') : t('trace.show_more', '展开完整段落')}
                                                                        </Button>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                );
                                            })
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                    </>
                )}
            </div>
        </div>
    );
};

export default AgentTracePanel;

function formatDuration(value: number): string {
    if (value === 0) return '< 1 ms';
    if (value < 1000) return `${Math.round(value)} ms`;
    return `${(value / 1000).toFixed(1)} s`;
}

function formatMetricValue(key: string, value: number | string | boolean): string {
    if (typeof value === 'boolean') return value ? 'yes' : 'no';
    if (typeof value === 'number') {
        if (key.endsWith('_ms')) return formatDuration(value);
        if (key === 'model_route_confidence') return `${(value * 100).toFixed(0)}%`;
        return String(value);
    }
    return value;
}

function getSummaryMetrics(traceSteps: AgentTraceStep[]) {
    const generateStep = traceSteps.find((step) => step.id === 'generate-answer');
    const completeStep = traceSteps.find((step) => step.id === 'complete');
    const firstToken = generateStep?.metricDetails?.first_token_latency_ms;
    const tokensPerSecond = completeStep?.metricDetails?.tokens_per_second;
    const items: Array<{ key: string; value: string }> = [];
    if (typeof firstToken === 'number') {
        items.push({ key: 'first_token', value: formatDuration(firstToken) });
    }
    if (completeStep?.durationMs !== undefined) {
        items.push({ key: 'total', value: formatDuration(completeStep.durationMs) });
    }
    if (typeof tokensPerSecond === 'number') {
        items.push({ key: 'tokens_per_second', value: tokensPerSecond.toFixed(2) });
    }
    return items;
}
