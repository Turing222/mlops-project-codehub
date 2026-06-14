import React, { useState, useEffect } from 'react';
import { Button, Popover, message as antdMessage } from 'antd';
import { LogOut, LogIn, Shield, Coins, Edit2, Database } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import { AppHttpError } from '../../lib/http/errors';
import { useChatController } from '../../features/chat/use-chat-controller';
import { useMyCreditsQuery, useDailyCheckinMutation } from '../../query/hooks/credits';
import Sidebar from './Sidebar';
import MessageList from './MessageList';
import AgentTracePanel from './AgentTracePanel';
import UserProfileModal from './UserProfileModal';
import KBFilesModal from './KBFilesModal';
import { FeatureGate } from '../../context/FeatureGate';
import styles from './ChatPage.module.css';

const ChatPage: React.FC = () => {
    const { user, isAuthenticated, logout, setShowAuthModal } = useAuth();
    const navigate = useNavigate();
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [tracePanelCollapsed, setTracePanelCollapsed] = useState(false);
    const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
    const [isKBModalOpen, setIsKBModalOpen] = useState(false);
    const { t } = useTranslation();

    const controller = useChatController();
    
    const lastAssistantMsg = React.useMemo(() => {
        return [...controller.messages]
            .reverse()
            .find((m) => m.role === 'assistant');
    }, [controller.messages]);

    const filteredCitations = React.useMemo(() => {
        const rawCitations = controller.citations;
        if (!lastAssistantMsg || !lastAssistantMsg.content) return [];
        
        const citationRegex = /\[[RW]\d+(?:\.\d+)?\]/g;
        const matches = lastAssistantMsg.content.match(citationRegex) || [];
        const mentionedIds = matches.map((match) => match.slice(1, -1));
        
        return rawCitations.filter((cit) => {
            const cleanId = cit.chunkId.replace(/[[]]/g, '');
            return mentionedIds.some((refId) => cleanId === refId || cleanId.startsWith(refId + '.'));
        });
    }, [controller.citations, lastAssistantMsg]);
    
    useEffect(() => {
        if (controller.isIngestionSidebarOpen) {
            setTracePanelCollapsed(false); // eslint-disable-line react-hooks/set-state-in-effect
            controller.setIsIngestionSidebarOpen(false);
        }
    }, [controller.isIngestionSidebarOpen, controller]);

    const { data: credits, isLoading: loadingCredits } = useMyCreditsQuery();
    const checkinMutation = useDailyCheckinMutation();

    const handleCheckin = async () => {
        try {
            const response = await checkinMutation.mutateAsync();
            antdMessage.success(t('credits.success_earn', { amount: response.amount_earned }));
        } catch (err: unknown) {
            if (err instanceof AppHttpError) {
                if (err.code === 'validation' && String(err.details).includes('ALREADY_CHECKED_IN')) {
                    antdMessage.warning(t('credits.checked_in_today'));
                }
                return;
            }
        }
    };

    const renderUserPopoverContent = () => {
        const usagePercent = Math.min(100, ((user?.used_tokens || 0) / (user?.max_tokens || 1)) * 100);
        return (
            <div className={styles['user-popover-content']}>
                {/* User Info Header */}
                <div
                    className={styles['user-popover-header']}
                    onClick={() => setIsProfileModalOpen(true)}
                    style={{ cursor: 'pointer' }}
                >
                    <div className={styles['popover-avatar']}>
                        {user?.username?.[0]?.toUpperCase()}
                    </div>
                    <div className={styles['popover-user-details']} style={{ flex: 1 }}>
                        <div className={styles['popover-username']} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <span>{user?.username}</span>
                            <Edit2 size={12} style={{ opacity: 0.6 }} />
                        </div>
                        <div className={styles['popover-email']}>{user?.email || t('chat.user_menu.user_role', '普通用户')}</div>
                    </div>
                </div>

                {/* Credits Section */}
                <FeatureGate flag="enable-credits">
                    <div className={styles['popover-section']}>
                        <div className={styles['popover-section-header']}>
                            <div
                                className={styles['popover-section-title-link']}
                                onClick={() => navigate('/credits')}
                            >
                                <Coins size={14} className={styles['popover-coin-icon']} />
                                <span>{t('credits.title')} ↗</span>
                            </div>
                        </div>
                        <div className={styles['popover-credit-balance-card']}>
                            <div style={{ display: 'flex', flexDirection: 'column' }}>
                                <span style={{ fontSize: '11px', color: 'var(--color-text-desc)', marginBottom: '2px' }}>
                                    {t('credits.my_balance', '当前可用积分')}
                                </span>
                                <div className={styles['popover-credit-balance-value']}>
                                    {loadingCredits ? '—' : (credits?.balance ?? 0)}
                                </div>
                            </div>
                            {credits?.is_checked_in_today ? (
                                <Button
                                    type="primary"
                                    size="small"
                                    className={styles['popover-recharge-btn']}
                                    style={{ opacity: 0.7, cursor: 'default' }}
                                    onClick={() => antdMessage.info(t('credits.checked_in_today', '今日已签到'))}
                                >
                                    {t('credits.checked_in_today', '已签到')}
                                </Button>
                            ) : (
                                <Button
                                    type="primary"
                                    size="small"
                                    className={styles['popover-recharge-btn']}
                                    loading={checkinMutation.isPending}
                                    onClick={handleCheckin}
                                >
                                    {t('credits.checkin_btn', '签到领积分')}
                                </Button>
                            )}
                        </div>
                    </div>
                </FeatureGate>

                {/* Token Usage Section */}
                <div className={styles['popover-section']}>
                    <div className={styles['popover-section-title']}>
                        {t('chat.user_menu.token_quota')}
                    </div>
                    <div className={styles['popover-token-usage']}>
                        <span>{t('chat.user_menu.used')}</span>
                        <span>{user?.used_tokens || 0} / {user?.max_tokens || 0}</span>
                    </div>
                    <div className={styles['popover-progress-bar']}>
                        <div
                            className={styles['popover-progress-fill']}
                            style={{ width: `${usagePercent}%` }}
                        />
                    </div>
                </div>

                {/* Action Buttons Section */}
                <div className={styles['popover-actions']}>
                    <Button
                        type="text"
                        icon={<Database size={14} />}
                        className={styles['popover-action-btn']}
                        onClick={() => setIsKBModalOpen(true)}
                    >
                        {t('chat.manage_kb_files', '管理知识库文档')}
                    </Button>
                    {user?.is_superuser && (
                        <Button
                            type="text"
                            icon={<Shield size={14} />}
                            className={styles['popover-action-btn']}
                            onClick={() => navigate('/admin')}
                        >
                            {t('chat.user_menu.admin_panel')}
                        </Button>
                    )}
                    <Button
                        type="text"
                        danger
                        icon={<LogOut size={14} />}
                        className={styles['popover-action-btn']}
                        onClick={() => {
                            logout();
                            antdMessage.success(t('chat.user_menu.logout'));
                        }}
                    >
                        {t('chat.user_menu.logout')}
                    </Button>
                </div>
            </div>
        );
    };


    return (
        <div className={`${styles['chat-page']} chat-page`}>
            <Sidebar
                activeSessionId={controller.activeSessionId}
                onSelectSession={controller.selectSession}
                onNewChat={controller.startNewChat}
                collapsed={sidebarCollapsed}
                onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
            />
            <div className={styles['chat-workspace']}>
                <div className={styles['chat-main']}>
                    <div className={styles['chat-header']}>
                        <div className={styles['chat-header-title-container']}>
                            <div className={`${styles['chat-header-title']} chat-header-title`}>
                                {controller.activeSession?.title || t('chat.default_title')}
                            </div>
                            {controller.activeSession && (
                                <div className={`${styles['chat-header-badge']} ${controller.chatMode !== 'normal' ? styles['rag'] : styles['normal']}`}>
                                    {controller.chatMode === 'web_rag'
                                        ? t('chat.mode_web_rag', '增强 RAG')
                                        : controller.activeSession.kb_id
                                            ? t('chat.mode_rag', '知识库问答 RAG')
                                            : t('chat.mode_normal', '普通对话')}
                                </div>
                            )}
                            {controller.activeSession && controller.activeSession.total_tokens !== undefined && (
                                <div className={styles['chat-header-tokens']}>
                                    {t('chat.tokens_consumed', { tokens: controller.activeSession.total_tokens })}
                                </div>
                            )}
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            {isAuthenticated ? (
                                <Popover
                                    content={renderUserPopoverContent()}
                                    placement="bottomRight"
                                    trigger="hover"
                                >
                                    <Button
                                        type="text"
                                        className={styles['user-menu-btn']}
                                        data-testid="user-menu-btn"
                                        icon={
                                            <div className={`${styles['avatar-badge']} avatar-badge`}>
                                                {user?.username?.[0]?.toUpperCase()}
                                            </div>
                                        }
                                    />
                                </Popover>
                            ) : (
                                <Button
                                    type="text"
                                    className={styles['user-menu-btn']}
                                    data-testid="user-menu-btn"
                                    onClick={() => setShowAuthModal(true)}
                                    icon={
                                        <div className={`${styles['avatar-badge']} avatar-badge ${styles['guest']} guest`}>
                                            <LogIn size={18} />
                                        </div>
                                    }
                                />
                            )}
                        </div>
                    </div>
                    <MessageList
                        messages={controller.messages}
                        streamingText={controller.streamingText}
                        isStreaming={controller.isStreaming}
                        isLoading={controller.isLoadingHistory}
                        onSend={controller.sendQuery}
                        onRetryFailedMessage={controller.retryFailedMessage}
                        chatMode={controller.chatMode}
                        setChatMode={controller.setChatMode}
                        onUploadKBFile={controller.uploadKBFile}
                        isIngesting={controller.isIngesting}
                    />
                </div>
                <FeatureGate flag="enable-agent-trace">
                    <AgentTracePanel
                        traceSteps={controller.traceSteps}
                        citations={filteredCitations}
                        ingestionSteps={controller.ingestionSteps}
                        activeTraceTab={controller.activeTraceTab}
                        setActiveTraceTab={controller.setActiveTraceTab}
                        collapsed={tracePanelCollapsed}
                        onToggle={() => setTracePanelCollapsed(!tracePanelCollapsed)}
                    />
                </FeatureGate>
            </div>
            <UserProfileModal
                isOpen={isProfileModalOpen}
                onClose={() => setIsProfileModalOpen(false)}
            />
            <KBFilesModal
                visible={isKBModalOpen}
                onClose={() => setIsKBModalOpen(false)}
            />
        </div>
    );
};

export default ChatPage;
