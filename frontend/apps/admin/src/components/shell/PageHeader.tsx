import React from 'react';
import styles from './PageHeader.module.css';

interface PageHeaderProps {
    title: React.ReactNode;
    icon?: React.ReactNode;
    actions?: React.ReactNode;
}

/** 内容区页头:标题(h2 + 图标)+ 右侧操作区(admin.md §2 Card Header)。 */
const PageHeader: React.FC<PageHeaderProps> = ({ title, icon, actions }) => (
    <div className={styles['page-header']}>
        <h2 className={styles.title}>
            {icon}
            {title}
        </h2>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
);

export default PageHeader;
