import React from 'react';
import styles from './Container.module.css';

interface ContainerProps {
    /** admin=1600(dense) / content=880(阅读型页面,C 档接入) */
    variant?: 'admin' | 'content';
    className?: string;
    children: React.ReactNode;
}

/** 内容版心:统一 max-width 与页内边距(spacing.json usage.admin)。 */
const Container: React.FC<ContainerProps> = ({ variant = 'admin', className, children }) => (
    <div className={`${styles.container} ${styles[variant]} ${className ?? ''}`.trim()}>
        {children}
    </div>
);

export default Container;
