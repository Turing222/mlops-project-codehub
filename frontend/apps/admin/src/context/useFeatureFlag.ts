import { useAuth } from './useAuth';

/**
 * 极简 Hook：用于在任何 JS 逻辑里动态判断 Feature Flag。
 * 如果用户未登录，或者 features 字典里没有配置，默认安全返回 false。
 *
 * Convention: A missing or undefined flag key is treated as `false` (safe default).
 * New features are opt-in — they must be explicitly enabled via the backend
 * FeatureFlagService to become visible to users.
 */
export const useFeatureFlag = (key: string): boolean => {
    const { user } = useAuth();
    return !!user?.features?.[key];
};
