import React from 'react';

import { useFeatureFlag } from './useFeatureFlag';

interface FeatureGateProps {
    flag: string;
    fallback?: React.ReactNode;
    children: React.ReactNode;
}

/**
 * 极简哨兵组件：用于在 UI 渲染中声明式隐藏或切换组件。
 */
export const FeatureGate: React.FC<FeatureGateProps> = ({ flag, fallback = null, children }) => {
    const isEnabled = useFeatureFlag(flag);
    return isEnabled ? <>{children}</> : <>{fallback}</>;
};
