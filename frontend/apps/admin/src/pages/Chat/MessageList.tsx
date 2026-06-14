import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Input, Button, Spin, Avatar, Upload, Popover } from 'antd';
import { Send, Bot, User as UserIcon, Paperclip, AlertCircle, RotateCcw, MessageSquare, Database, Globe2, Github } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatMessage } from '../../types/chat';
import type { ChatMode } from '../../features/chat/use-chat-controller';
import { parseCitations } from '../../types/agent-trace';
import styles from './MessageList.module.css';
import PixelAvatar from './PixelAvatar';
import { FeatureGate } from '../../context/FeatureGate';
import RepoAnalysisCard from '../RepoCheck/RepoAnalysisCard';


const { TextArea } = Input;

interface MessageListProps {
    messages: ChatMessage[];
    streamingText: string;
    isStreaming: boolean;
    isLoading: boolean;
    onSend: (text: string) => void;
    onRetryFailedMessage?: (messageId: string) => void;
    chatMode: ChatMode;
    setChatMode: (mode: ChatMode) => void;
    onUploadKBFile?: (file: File) => Promise<void>;
    isIngesting?: boolean;
}

const MessageList: React.FC<MessageListProps> = ({
    messages,
    streamingText,
    isStreaming,
    isLoading,
    onSend,
    onRetryFailedMessage,
    chatMode,
    setChatMode,
    onUploadKBFile,
    isIngesting = false,
}) => {
    const navigate = useNavigate();
    const [inputValue, setInputValue] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const { t } = useTranslation();

    const renderMessageContent = useCallback((content: string, searchContext?: Record<string, unknown>) => {
        if (!content) return '';
        const citations = searchContext ? parseCitations(searchContext) : [];
        const citationRegex = /\[[RW]\d+(?:\.\d+)?\]/g;
        
        const parts = [];
        let lastIndex = 0;
        let match;
        
        while ((match = citationRegex.exec(content)) !== null) {
            const matchIndex = match.index;
            const matchText = match[0];
            
            if (matchIndex > lastIndex) {
                parts.push(content.substring(lastIndex, matchIndex));
            }
            
            const refIdStr = matchText.slice(1, -1);
            
            const citation = citations.find(c => {
                const cleanId = c.chunkId.replace(/[[]]/g, '');
                return cleanId === refIdStr || cleanId.startsWith(refIdStr + '.');
            });
            
            if (citation) {
                const scorePercent = citation.relevanceScore
                    ? `${Math.round(citation.relevanceScore * 100)}%`
                    : 'N/A';
                    
                const isWeb = Boolean(citation.url) || citation.chunkId.startsWith('W');
                const pageLabel = (citation.metaInfo?.page_label as string | undefined) || (citation.metaInfo?.page as string | number | undefined);
                const locationText = isWeb
                    ? ''
                    : pageLabel
                    ? `(${t('chat.page_label', '第')} ${pageLabel} ${t('chat.page_unit', '页')})`
                    : (typeof citation.chunkIndex === 'number' ? `(${t('chat.chunk_label', '第')} ${citation.chunkIndex + 1} ${t('chat.chunk_unit', '段')})` : '');

                const sectionPath = citation.metaInfo?.section_path as string | undefined;
                
                const popoverContent = (
                    <div className={styles['citation-popover-content']}>
                        <div className={styles['citation-popover-header']}>
                            {isWeb ? (
                                <Globe2 size={14} className={styles['popover-icon']} />
                            ) : (
                                <Database size={14} className={styles['popover-icon']} />
                            )}
                            <span className={styles['popover-filename']} title={`${citation.documentName} ${locationText}`}>
                                {citation.documentName} <span className={styles['popover-location']}>{locationText}</span>
                            </span>
                            {citation.relevanceScore > 0 && (
                                <span className={styles['popover-score']}>
                                    {scorePercent} {t('chat.similarity', '相关度')}
                                </span>
                            )}
                        </div>
                        {sectionPath && (
                            <div className={styles['popover-section-path']} title={sectionPath}>
                                <span className={styles['section-path-label']}>{t('chat.section_path_label', '📖 Section:')}</span>
                                <span className={styles['section-path-value']}>{sectionPath}</span>
                            </div>
                        )}
                        {citation.summarySnippet && (
                            <div className={styles['popover-snippet']}>
                                {citation.summarySnippet.length > 100
                                    ? `${citation.summarySnippet.slice(0, 100)}...`
                                    : citation.summarySnippet}
                            </div>
                        )}
                    </div>
                );
                
                parts.push(
                    <Popover
                        key={`citation-${matchIndex}`}
                        content={popoverContent}
                        title={null}
                        trigger={['hover', 'click']}
                        placement="top"
                        overlayClassName={styles['citation-popover-overlay']}
                    >
                        <span className={styles['citation-badge']}>
                            {matchText}
                        </span>
                    </Popover>
                );
            } else {
                parts.push(
                    <span key={`citation-fallback-${matchIndex}`} className={styles['citation-badge-fallback']}>
                        {matchText}
                    </span>
                );
            }
            
            lastIndex = citationRegex.lastIndex;
        }
        
        if (lastIndex < content.length) {
            parts.push(content.substring(lastIndex));
        }
        
        return parts.length > 0 ? parts : content;
    }, [t]);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, streamingText]);

    const handleSend = () => {
        const text = inputValue.trim();
        if (!text || isStreaming) return;
        onSend(text);
        setInputValue('');
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleUpload = (file: File) => {
        if (onUploadKBFile) {
            void onUploadKBFile(file);
        }
        return false;
    };

    const renderMessage = (msg: ChatMessage) => {
        const isUser = msg.role === 'user';
        const isRepoCheck = msg.message_metadata?.type === 'repo_check_run';

        if (isRepoCheck) {
            return (
                <div key={msg.id} className={`${styles['chat-message']} chat-message ${styles.assistant} assistant`} style={{ maxWidth: '840px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                        <div className={styles['assistant-avatar-wrapper']}>
                            <Avatar
                                className={styles['chat-avatar']}
                                style={{ backgroundColor: 'var(--color-bg-subtle)', flexShrink: 0 }}
                                icon={<Bot size={18} color="var(--color-primary)" />}
                            />
                        </div>
                        <strong style={{ color: 'var(--color-text-main)', fontSize: '14px' }}>
                            {t('repo_check.page_title', 'AI 项目可信度初筛报告')}
                        </strong>
                    </div>
                    <div style={{ width: '100%', paddingLeft: '48px', boxSizing: 'border-box' }}>
                        <RepoAnalysisCard runId={msg.message_metadata?.run_id as string} />
                    </div>
                </div>
            );
        }

        return (
            <div key={msg.id} className={`${styles['chat-message']} chat-message ${isUser ? `${styles.user} user` : `${styles.assistant} assistant`}`}>
                {isUser ? (
                    <Avatar
                        className={styles['chat-avatar']}
                        style={{ backgroundColor: 'var(--color-bg-subtle)', flexShrink: 0 }}
                        icon={<UserIcon size={18} color="var(--color-primary)" />}
                    />
                ) : (
                    <div className={styles['assistant-avatar-wrapper']}>
                        <FeatureGate
                            flag="enable-pixel-avatar"
                            fallback={
                                <Avatar
                                    className={styles['chat-avatar']}
                                    style={{ backgroundColor: 'var(--color-bg-subtle)', flexShrink: 0 }}
                                    icon={<Bot size={18} color="var(--color-primary)" />}
                                />
                            }
                        >
                            <PixelAvatar 
                                isStreaming={false} 
                                isUserTyping={inputValue.trim().length > 0} 
                            />
                        </FeatureGate>
                    </div>
                )}
                <div className={`${styles['chat-bubble']} ${isUser ? styles['user-bubble'] : styles['assistant-bubble']}`}>
                    {msg.status === 'failed' ? (
                        <>
                            <div className={styles['error-content']}>
                                <AlertCircle size={14} />
                                <span>{msg.content || t('chat.request_failed')}</span>
                            </div>
                            {!isUser && onRetryFailedMessage && (
                                <div className={styles['error-actions']}>
                                    <Button
                                        type="link"
                                        className={styles['retry-btn']}
                                        icon={<RotateCcw size={14} />}
                                        onClick={() => onRetryFailedMessage(msg.id)}
                                        disabled={isStreaming}
                                    >
                                        {t('chat.retry')}
                                    </Button>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className={`${styles['message-text']} message-text`}>
                            {renderMessageContent(msg.content, msg.search_context ?? undefined)}
                        </div>
                    )}
                    {msg.latency_ms && (
                        <div className={styles['message-meta']}>{msg.latency_ms}ms</div>
                    )}
                </div>
            </div>
        );
    };

    return (
        <div className={styles['message-list-container']}>
            <div className={styles['messages-scroll']}>
                {isLoading ? (
                    <div className={styles['messages-loading']}>
                        <Spin size="large" />
                        <span className={styles['loading-label']}>{t('chat.loading_history')}</span>
                    </div>
                ) : messages.length === 0 && !isStreaming ? (
                    <div className={styles['messages-empty']}>
                        <div className={styles['empty-hint']}>
                            <Bot size={40} className={styles['empty-hint-icon']} />
                            <h3>{t('chat.empty_title')}</h3>
                            <p>{t('chat.empty_desc1')}</p>
                            <p className={styles['empty-sub-prompt']}>{t('chat.empty_desc2')}</p>
                        </div>
                        <div className={styles['mode-selector-container']}>
                            <div
                                className={`${styles['mode-card']} ${chatMode === 'normal' ? styles.active : ''}`}
                                onClick={() => setChatMode('normal')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <MessageSquare size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_normal_title', '普通对话')}</h4>
                                    <p>{t('chat.mode_normal_desc', '纯粹的大语言模型对话，速度极快，不绑定任何特定文档。')}</p>
                                </div>
                            </div>

                            <div
                                className={`${styles['mode-card']} ${chatMode === 'rag' ? styles.active : ''}`}
                                onClick={() => setChatMode('rag')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <Database size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_rag_title', '知识库问答 RAG')}</h4>
                                    <p>{t('chat.mode_rag_desc', '关联您的默认个人知识库文档，回答更有针对性与专业性。')}</p>
                                </div>
                            </div>

                            <div
                                className={`${styles['mode-card']} ${chatMode === 'web_rag' ? styles.active : ''}`}
                                onClick={() => setChatMode('web_rag')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <Globe2 size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_web_rag_title', '增强 RAG')}</h4>
                                    <p>{t('chat.mode_web_rag_desc', '结合知识库与按需联网检索，适合需要最新公开信息的问题。')}</p>
                                </div>
                            </div>

                            <div
                                className={`${styles['mode-card']} ${chatMode === 'repo_check' ? styles.active : ''}`}
                                onClick={() => navigate('/repo-check')}
                            >
                                <div className={styles['mode-card-icon-container']}>
                                    <Github size={20} className={styles['mode-icon']} />
                                </div>
                                <div className={styles['mode-card-content']}>
                                    <h4>{t('chat.mode_repo_check_title', '仓库可信度初筛')}</h4>
                                    <p>{t('chat.mode_repo_check_desc', '输入公开 GitHub 仓库，生成基于 README 和元信息的非技术信用评估报告。')}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                ) : (
                    <>
                        {messages.map(renderMessage)}
                        {isStreaming && streamingText && (
                            <div className={`${styles['chat-message']} chat-message ${styles.assistant} assistant`}>
                                <div className={styles['assistant-avatar-wrapper']}>
                                    <FeatureGate
                                        flag="enable-pixel-avatar"
                                        fallback={
                                            <Avatar
                                                className={styles['chat-avatar']}
                                                style={{ backgroundColor: 'var(--color-bg-subtle)', flexShrink: 0 }}
                                                icon={<Bot size={18} color="var(--color-primary)" />}
                                            />
                                        }
                                    >
                                        <PixelAvatar isStreaming={true} isUserTyping={false} />
                                    </FeatureGate>
                                </div>
                                <div className={`${styles['chat-bubble']} ${styles['assistant-bubble']}`}>
                                    <div className={`${styles['message-text']} message-text`}>
                                        {renderMessageContent(streamingText)}
                                        <span className={styles['cursor-blink']}>|</span>
                                    </div>
                                </div>
                            </div>
                        )}
                        {isStreaming && !streamingText && (
                            <div className={`${styles['chat-message']} chat-message ${styles.assistant} assistant`}>
                                <div className={styles['assistant-avatar-wrapper']}>
                                    <FeatureGate
                                        flag="enable-pixel-avatar"
                                        fallback={
                                            <Avatar
                                                className={styles['chat-avatar']}
                                                style={{ backgroundColor: 'var(--color-bg-subtle)', flexShrink: 0 }}
                                                icon={<Bot size={18} color="var(--color-primary)" />}
                                            />
                                        }
                                    >
                                        <PixelAvatar isStreaming={true} isUserTyping={false} />
                                    </FeatureGate>
                                </div>
                                <div className={`${styles['chat-bubble']} ${styles['assistant-bubble']}`}>
                                    <div className={styles['thinking-dots']}>
                                        <span></span><span></span><span></span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </>
                )}
                <div ref={messagesEndRef} />
            </div>

            <div className={styles['input-area']}>
                <div className={styles['input-container-wrapper']}>
                    <div className={`${styles['input-row']} ${isStreaming || isIngesting ? styles['input-disabled'] : ''}`}>
                        <Upload
                            showUploadList={false}
                            beforeUpload={handleUpload}
                            accept=".md,.markdown"
                            disabled={isStreaming || isIngesting}
                        >
                            <Button
                                className={styles['upload-btn']}
                                icon={<Paperclip size={18} />}
                                type="text"
                                title={t('chat.upload_file')}
                                disabled={isStreaming || isIngesting}
                            />
                        </Upload>
                        <TextArea
                            className={styles['chat-input']}
                            data-testid="chat-input"
                            value={inputValue}
                            onChange={(e) => setInputValue(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={chatMode === 'repo_check' ? t('repo_check.chat_input_tip', '请输入公开 GitHub 仓库地址 (例如 https://github.com/owner/repo) 并回车评估...') : t('chat.input_tip')}
                            autoSize={{ minRows: 1, maxRows: 4 }}
                            disabled={isStreaming}
                        />
                        <Button
                            className={styles['send-btn']}
                            type="primary"
                            data-testid="send-btn"
                            icon={<Send size={18} />}
                            onClick={handleSend}
                            disabled={!inputValue.trim() || isStreaming}
                            loading={isStreaming}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MessageList;
