import React, { useCallback, useEffect, useState } from 'react';
import { Button, Spin, Tooltip } from 'antd';
import { Plus, MessageSquare, Clock, ChevronLeft, ChevronRight } from 'lucide-react';
import type { ChatSession } from '../../types/chat';
import { getSessionsAPI } from '../../api/chat';
import { useAuth } from '../../context/useAuth';
import './Sidebar.css';

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
    const { isAuthenticated } = useAuth();
    const [sessions, setSessions] = useState<ChatSession[]>([]);
    const [loading, setLoading] = useState(false);

    const loadSessions = useCallback(async () => {
        if (!isAuthenticated) return;
        setLoading(true);
        try {
            const res = await getSessionsAPI(0, 50);
            setSessions(res.items || []);
        } catch {
            // handled
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    useEffect(() => {
        void loadSessions();
    }, [loadSessions]);

    // Expose refresh
    useEffect(() => {
        window.__refreshSidebar = loadSessions;
        return () => {
            delete window.__refreshSidebar;
        };
    }, [loadSessions]);

    const formatTime = (dateStr: string) => {
        const d = new Date(dateStr);
        const now = new Date();
        const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
        if (diffDays === 0) return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
        if (diffDays === 1) return '昨天';
        if (diffDays < 7) return `${diffDays}天前`;
        return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
    };

    if (collapsed) {
        return (
            <div className="sidebar collapsed-sidebar">
                <Button
                    className="toggle-btn"
                    type="text"
                    icon={<ChevronRight size={18} />}
                    onClick={onToggle}
                />
                <Tooltip title="新对话" placement="right">
                    <Button
                        className="collapsed-action-btn"
                        type="text"
                        icon={<Plus size={20} />}
                        onClick={onNewChat}
                    />
                </Tooltip>
            </div>
        );
    }

    return (
        <div className="sidebar">
            <div className="sidebar-header">
                <Button
                    className="new-chat-btn"
                    type="primary"
                    icon={<Plus size={16} />}
                    onClick={onNewChat}
                    block
                >
                    新对话
                </Button>
                <Button
                    className="toggle-btn"
                    type="text"
                    icon={<ChevronLeft size={18} />}
                    onClick={onToggle}
                />
            </div>

            <div className="sidebar-section-title">
                <Clock size={14} />
                <span>历史记录</span>
            </div>

            <div className="session-list">
                {!isAuthenticated ? (
                    <div className="sidebar-hint">登录后可查看历史记录</div>
                ) : loading ? (
                    <div className="sidebar-loading"><Spin size="small" /></div>
                ) : sessions.length === 0 ? (
                    <div className="sidebar-hint">暂无对话记录</div>
                ) : (
                    sessions.map((s) => (
                        <div
                            key={s.id}
                            className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
                            onClick={() => onSelectSession(s)}
                        >
                            <MessageSquare size={14} className="session-icon" />
                            <div className="session-info">
                                <div className="session-title">{s.title}</div>
                                <div className="session-time">{formatTime(s.updated_at)}</div>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
};

export default Sidebar;
