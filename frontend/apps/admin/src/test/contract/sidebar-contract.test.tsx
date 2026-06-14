import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';

import Sidebar from '../../pages/Chat/Sidebar';
import { useAuthStore } from '../../stores/auth-store';
import { setAccessToken } from '../../lib/http/auth';
import { renderForContract } from '../render-with-query';

const noop = vi.fn();

describe('Sidebar contract', () => {
    beforeEach(() => {
        useAuthStore.getState().resetAll();
    });

    it('authenticated user sees sessions from API in sidebar', async () => {
        setAccessToken('test-access-token');

        renderForContract(
            <Sidebar
                activeSessionId={null}
                onSelectSession={noop}
                onNewChat={noop}
                collapsed={false}
                onToggle={noop}
            />,
        );

        await waitFor(() => {
            expect(screen.getByText('Session 1')).toBeInTheDocument();
        });

        expect(screen.getByText('Session 2')).toBeInTheDocument();
        expect(screen.getByText('Session 3')).toBeInTheDocument();
    });

    it('unauthenticated user sees login hint', () => {
        renderForContract(
            <Sidebar
                activeSessionId={null}
                onSelectSession={noop}
                onNewChat={noop}
                collapsed={false}
                onToggle={noop}
            />,
        );

        expect(screen.getByText('登录后可查看历史记录')).toBeInTheDocument();
    });
});
