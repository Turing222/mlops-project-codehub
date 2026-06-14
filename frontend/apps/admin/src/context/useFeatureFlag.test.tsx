import { render, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useAuth } from './useAuth';
import { useFeatureFlag } from './useFeatureFlag';
import { FeatureGate } from './FeatureGate';

type AuthReturn = ReturnType<typeof useAuth>;

vi.mock('./useAuth', () => ({
    useAuth: vi.fn(),
}));

const mockUseAuth = vi.mocked(useAuth);

describe('useFeatureFlag', () => {
    it('returns true if the flag is enabled in user features', () => {
        mockUseAuth.mockReturnValue({
            user: {
                id: '1',
                username: 'alice',
                features: { 'enable-pixel-avatar': true },
            },
        } as Partial<AuthReturn> as AuthReturn);

        const { result } = renderHook(() => useFeatureFlag('enable-pixel-avatar'));
        expect(result.current).toBe(true);
    });

    it('returns false if the flag is disabled or missing in user features', () => {
        mockUseAuth.mockReturnValue({
            user: {
                id: '1',
                username: 'alice',
                features: { 'enable-pixel-avatar': false },
            },
        } as Partial<AuthReturn> as AuthReturn);

        const { result } = renderHook(() => useFeatureFlag('enable-pixel-avatar'));
        expect(result.current).toBe(false);

        const { result: missingResult } = renderHook(() => useFeatureFlag('enable-credits'));
        expect(missingResult.current).toBe(false);
    });

    it('returns false if user is logged out', () => {
        mockUseAuth.mockReturnValue({
            user: null,
        } as Partial<AuthReturn> as AuthReturn);

        const { result } = renderHook(() => useFeatureFlag('enable-pixel-avatar'));
        expect(result.current).toBe(false);
    });
});

describe('FeatureGate', () => {
    it('renders children when the flag is enabled', () => {
        mockUseAuth.mockReturnValue({
            user: {
                id: '1',
                username: 'alice',
                features: { 'enable-credits': true },
            },
        } as Partial<AuthReturn> as AuthReturn);

        const { queryByText } = render(
            <FeatureGate flag="enable-credits" fallback={<div>Fallback</div>}>
                <div>Content</div>
            </FeatureGate>
        );

        expect(queryByText('Content')).not.toBeNull();
        expect(queryByText('Fallback')).toBeNull();
    });

    it('renders fallback when the flag is disabled', () => {
        mockUseAuth.mockReturnValue({
            user: {
                id: '1',
                username: 'alice',
                features: { 'enable-credits': false },
            },
        } as Partial<AuthReturn> as AuthReturn);

        const { queryByText } = render(
            <FeatureGate flag="enable-credits" fallback={<div>Fallback</div>}>
                <div>Content</div>
            </FeatureGate>
        );

        expect(queryByText('Content')).toBeNull();
        expect(queryByText('Fallback')).not.toBeNull();
    });
});
