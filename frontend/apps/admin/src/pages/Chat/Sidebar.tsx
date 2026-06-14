import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Spin, Tooltip } from 'antd';
import { Plus, MessageSquare, Clock, ChevronLeft, ChevronRight, Inbox, Sun, Moon, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { ChatSession } from '../../types/chat';
import { useChatSessionsQuery } from '../../query/hooks/chat';
import { useAuth } from '../../context/useAuth';
import { useThemeStore } from '../../stores/theme-store';
import { changeAppLanguage } from '../../lib/i18n';
import styles from './Sidebar.module.css';

interface SidebarProps {
    activeSessionId: string | null;
    onSelectSession: (session: ChatSession) => void;
    onNewChat: () => void;
    collapsed: boolean;
    onToggle: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({
    activeSessionId,
    onSelectSession,
    onNewChat,
    collapsed,
    onToggle,
}) => {
    const navigate = useNavigate();
    const { isAuthenticated } = useAuth();
    const { data, isLoading: loading } = useChatSessionsQuery();
    const sessions = data?.items || [];
    const { theme, setTheme } = useThemeStore();
    const { t, i18n } = useTranslation();

    const formatTime = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
        const locale = i18n.language === 'en-US' ? 'en-US' : 'zh-CN';
        if (diffDays === 0) return d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
        if (diffDays === 1) return t('sidebar.time.yesterday');
        if (diffDays < 7) return t('sidebar.time.days_ago', { count: diffDays });
        return d.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    };

    const toggleLanguage = () => {
        const targetLng = i18n.language === 'zh-CN' ? 'en-US' : 'zh-CN';
        void changeAppLanguage(targetLng);
    };

    if (collapsed) {
        return (
            <div className={`${styles.sidebar} ${styles['collapsed-sidebar']}`}>
                <Button
                    className={styles['toggle-btn']}
                    type="text"
                    icon={<ChevronRight size={18} />}
                    aria-label={t('sidebar.expand')}
                    onClick={onToggle}
                />
                <Tooltip title={t('sidebar.new_chat')} placement="right">
                    <Button
                        className={styles['collapsed-action-btn']}
                        type="text"
                        icon={<Plus size={20} />}
                        onClick={onNewChat}
                    />
                </Tooltip>
                <Tooltip title={t('repo_check.page_title', '仓库可信度初筛')} placement="right">
                    <Button
                        className={styles['collapsed-action-btn']}
                        type="text"
                        icon={<ShieldCheck size={20} />}
                        onClick={() => navigate('/repo-check')}
                    />
                </Tooltip>
                
                <div style={{ flex: 1 }} />

                <div className={styles['collapsed-footer']}>
                    <Tooltip title={theme === 'dark' ? t('sidebar.light_mode') : t('sidebar.dark_mode')} placement="right">
                        <Button
                            className={styles['sidebar-footer-btn']}
                            type="text"
                            icon={theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
                            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                            data-testid="theme-toggle-btn"
                        />
                    </Tooltip>
                    <Tooltip title={i18n.language === 'zh-CN' ? 'Switch to English' : '切换为中文'} placement="right">
                        <Button
                            className={styles['sidebar-footer-btn']}
                            type="text"
                            onClick={toggleLanguage}
                            data-testid="language-toggle-btn"
                        >
                            <span className={styles['lang-toggle-text']}>
                                {i18n.language === 'zh-CN' ? 'EN' : '中'}
                            </span>
                        </Button>
                    </Tooltip>
                </div>
            </div>
        );
    }

    return (
        <div className={styles.sidebar}>
            <div className={styles['sidebar-header']}>
                <Button
                    className={styles['new-chat-btn']}
                    type="primary"
                    icon={<Plus size={16} />}
                    onClick={onNewChat}
                    block
                >
                    {t('sidebar.new_chat')}
                </Button>
                <Button
                    className={styles['toggle-btn']}
                    type="text"
                    icon={<ChevronLeft size={18} />}
                    aria-label={t('sidebar.collapse')}
                    onClick={onToggle}
                />
            </div>

            {/* 仓库可信度初筛入口 */}
            <div className={styles['workbench-card']} onClick={() => navigate('/repo-check')}>
                <div className={styles['workbench-card-glow']} />
                <div className={styles['workbench-card-icon']}>
                    <ShieldCheck size={18} />
                </div>
                <div className={styles['workbench-card-content']}>
                    <div className={styles['workbench-card-title']}>
                        {t('repo_check.sidebar_title', '仓库可信度初筛')}
                        <span className={styles['workbench-card-tag']}>Tool</span>
                    </div>
                    <div className={styles['workbench-card-desc']}>
                        {t('repo_check.sidebar_desc', 'README 信用评估')}
                    </div>
                </div>
            </div>

            <div className={styles['sidebar-section-title']}>
                <Clock size={14} />
                <span>{t('sidebar.history')}</span>
            </div>

            <div className={styles['session-list']}>
                {!isAuthenticated ? (
                    <div className={`${styles['sidebar-hint']} sidebar-hint`}>
                        {t('sidebar.login_hint')}
                    </div>
                ) : loading ? (
                    <div className={styles['sidebar-loading']}><Spin size="small" /></div>
                ) : sessions.length === 0 ? (
                    <div className={`${styles['sidebar-hint']} sidebar-hint`}>
                        <Inbox size={20} className={styles['sidebar-hint-icon']} />
                        {t('sidebar.empty_hint')}
                    </div>
                ) : (
                    sessions.map((s) => (
                        <div
                            key={s.id}
                            className={`${styles['session-item']} session-item ${s.id === activeSessionId ? `${styles.active} active` : ''}`}
                            role="button"
                            tabIndex={0}
                            aria-label={s.title}
                            aria-pressed={s.id === activeSessionId}
                            data-testid="session-item"
                            onClick={() => onSelectSession(s)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    onSelectSession(s);
                                }
                            }}
                        >
                            <MessageSquare size={14} className={styles['session-icon']} />
                            <div className={styles['session-info']}>
                                <div className={styles['session-title']}>{s.title}</div>
                                <div className={styles['session-time']}>{formatTime(s.updated_at)}</div>
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* 底部按钮：切换明暗 & 切换语言 */}
            <div className={styles['sidebar-footer']}>
                <Tooltip title={theme === 'dark' ? t('sidebar.light_mode') : t('sidebar.dark_mode')} placement="top">
                    <Button
                        className={styles['sidebar-footer-btn']}
                        type="text"
                        icon={theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                        data-testid="theme-toggle-btn"
                    />
                </Tooltip>
                <Tooltip title={i18n.language === 'zh-CN' ? 'Switch to English' : '切换为中文'} placement="top">
                    <Button
                        className={styles['sidebar-footer-btn']}
                        type="text"
                        onClick={toggleLanguage}
                        data-testid="language-toggle-btn"
                    >
                        <span className={styles['lang-toggle-text']}>
                            {i18n.language === 'zh-CN' ? 'EN' : '中'}
                        </span>
                    </Button>
                </Tooltip>
            </div>
        </div>
    );
};

export default Sidebar;
