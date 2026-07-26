import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Drawer } from 'antd';
import { Coins, Menu, MessageSquare, Shield, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import styles from './AppShell.module.css';

interface AppShellProps {
    /** 顶栏当前页标题;Admin 页会附加 .header-title e2e 钩子 */
    pageTitle: string;
    pageIcon?: React.ReactNode;
    /** 附加到根节点的裸 class(如 admin-layout e2e 钩子) */
    rootClassName?: string;
    children: React.ReactNode;
}

/**
 * 管理侧应用外壳(dense · crisp):深色 56px 顶栏 + 全局导航 + 内容区。
 * Chat 页不使用本壳(calm 轨,全局导航在其 Sidebar 内)。
 * 规范:design/patterns/admin.md §1 Shell。
 */
const AppShell: React.FC<AppShellProps> = ({ pageTitle, pageIcon, rootClassName, children }) => {
    const navigate = useNavigate();
    const location = useLocation();
    const { user } = useAuth();
    const { t } = useTranslation();
    const [drawerOpen, setDrawerOpen] = React.useState(false);

    const goTo = (path: string) => {
        setDrawerOpen(false);
        navigate(path);
    };

    const navItems = [
        { path: '/', label: t('nav.chat', '对话'), icon: <MessageSquare size={16} /> },
        { path: '/credits', label: t('nav.credits', '积分中心'), icon: <Coins size={16} /> },
        { path: '/repo-check', label: t('nav.repo_check', '仓库分析'), icon: <ShieldCheck size={16} /> },
        ...(user?.is_superuser
            ? [{ path: '/admin', label: t('nav.admin', '管理后台'), icon: <Shield size={16} /> }]
            : []),
    ];

    return (
        <div className={`${styles.shell} ${rootClassName ?? ''}`.trim()}>
            <header className={styles.header}>
                <div className={styles['header-left']}>
                    <button
                        type="button"
                        className={styles['drawer-trigger']}
                        onClick={() => setDrawerOpen(true)}
                        aria-label={t('nav.open_menu', '打开导航')}
                    >
                        <Menu size={20} />
                    </button>
                    <button
                        type="button"
                        className={styles.logo}
                        onClick={() => goTo('/')}
                        aria-label={t('nav.chat', '对话')}
                    >
                        <Shield size={20} color="var(--color-primary)" />
                        <span className={styles['logo-text']}>Dewflow</span>
                    </button>
                    <nav className={styles.nav} aria-label={t('nav.aria_label', '全局导航')}>
                        {navItems.map((item) => (
                            <button
                                key={item.path}
                                type="button"
                                className={`${styles['nav-item']} ${
                                    location.pathname === item.path ? styles['nav-item-active'] : ''
                                }`.trim()}
                                onClick={() => goTo(item.path)}
                                aria-current={location.pathname === item.path ? 'page' : undefined}
                            >
                                {item.icon}
                                <span>{item.label}</span>
                            </button>
                        ))}
                    </nav>
                </div>
                <div className={styles['header-right']}>
                    <span className={`${styles['page-title']} header-title`}>
                        {pageIcon}
                        <span>{pageTitle}</span>
                    </span>
                    {user?.username ? (
                        <span className={styles['header-user']}>{user.username}</span>
                    ) : null}
                </div>
            </header>
            <main className={styles.main}>{children}</main>
            <Drawer
                placement="left"
                width={240}
                open={drawerOpen}
                onClose={() => setDrawerOpen(false)}
                title="Dewflow"
                styles={{ body: { padding: 'var(--space-2)' } }}
            >
                <nav className={styles['drawer-nav']} aria-label={t('nav.aria_label', '全局导航')}>
                    {navItems.map((item) => (
                        <button
                            key={item.path}
                            type="button"
                            className={`${styles['drawer-nav-item']} ${
                                location.pathname === item.path ? styles['drawer-nav-item-active'] : ''
                            }`.trim()}
                            onClick={() => goTo(item.path)}
                        >
                            {item.icon}
                            <span>{item.label}</span>
                        </button>
                    ))}
                </nav>
            </Drawer>
        </div>
    );
};

export default AppShell;
