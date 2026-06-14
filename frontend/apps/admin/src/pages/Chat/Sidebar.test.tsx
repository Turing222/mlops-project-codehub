import { describe, expect, it, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BrowserRouter } from 'react-router-dom';
import Sidebar from './Sidebar';
import styles from './Sidebar.module.css';
import { renderWithQueryClient } from '../../test/render-with-query';
import type { ChatSession } from '../../types/chat';

vi.mock('../../context/useAuth', () => ({
    useAuth: vi.fn(),
}));

vi.mock('../../query/hooks/chat', () => ({
    useChatSessionsQuery: vi.fn(),
}));

import { useAuth } from '../../context/useAuth';
import { useChatSessionsQuery } from '../../query/hooks/chat';

const mockUseAuth = vi.mocked(useAuth);
const mockUseChatSessionsQuery = vi.mocked(useChatSessionsQuery);

type AuthReturn = ReturnType<typeof useAuth>;
type ChatSessionsReturn = ReturnType<typeof useChatSessionsQuery>;

const fakeSessions: ChatSession[] = [
    {
        id: 's1',
        title: 'Session 1',
        user_id: 'u1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    },
    {
        id: 's2',
        title: 'Session 2',
        user_id: 'u1',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    },
];

const defaultAuth: AuthReturn = {
    user: null,
    token: null,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: false,
    showAuthModal: false,
    setShowAuthModal: vi.fn(),
    refreshUser: vi.fn(),
};

function makeQueryResult(overrides: Partial<ChatSessionsReturn> = {}): ChatSessionsReturn {
    return {
        data: undefined,
        dataUpdatedAt: 0,
        error: null,
        errorUpdatedAt: 0,
        failureCount: 0,
        failureReason: null,
        errorUpdateCount: 0,
        isError: false,
        isFetched: false,
        isFetchedAfterMount: false,
        isFetching: false,
        isPaused: false,
        isLoading: false,
        isLoadingError: false,
        isInitialLoading: false,
        isPending: true,
        isPlaceholderData: false,
        isRefetchError: false,
        isRefetching: false,
        isStale: false,
        isSuccess: false,
        refetch: vi.fn(),
        status: 'pending',
        fetchStatus: 'idle',
        promise: Promise.resolve(undefined),
        ...overrides,
    } as ChatSessionsReturn;
}

function renderSidebar(overrides: Record<string, unknown> = {}) {
    const props = {
        activeSessionId: null,
        onSelectSession: vi.fn(),
        onNewChat: vi.fn(),
        collapsed: false,
        onToggle: vi.fn(),
        ...overrides,
    };
    const result = renderWithQueryClient(
        <BrowserRouter>
            <Sidebar {...props} />
        </BrowserRouter>
    );
    return { ...result, props };
}

beforeEach(() => {
    mockUseAuth.mockReturnValue(defaultAuth);
    mockUseChatSessionsQuery.mockReturnValue(makeQueryResult());
});

describe('Sidebar', () => {
    it('shows login hint when not authenticated', () => {
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: false });
        renderSidebar();
        expect(screen.getByText('登录后可查看历史记录')).toBeInTheDocument();
    });

    it('shows spinner when loading', () => {
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            isLoading: true,
            isPending: true,
            isFetching: true,
            status: 'pending',
            fetchStatus: 'fetching',
        }));
        renderSidebar();
        expect(document.querySelector('.ant-spin')).toBeInTheDocument();
    });

    it('shows empty hint when no sessions', () => {
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            data: { items: [], total: 0, skip: 0, limit: 50 } as ChatSessionsReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        renderSidebar();
        expect(screen.getByText('暂无对话记录')).toBeInTheDocument();
    });

    it('renders session list when sessions exist', () => {
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            data: { items: fakeSessions, total: 2, skip: 0, limit: 50 } as ChatSessionsReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        renderSidebar();
        expect(screen.getByText('Session 1')).toBeInTheDocument();
        expect(screen.getByText('Session 2')).toBeInTheDocument();
        expect(document.querySelectorAll('.' + styles['session-item'])).toHaveLength(2);
    });

    it('highlights active session', () => {
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            data: { items: fakeSessions, total: 2, skip: 0, limit: 50 } as ChatSessionsReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        renderSidebar({ activeSessionId: 's1' });
        const activeItem = document.querySelector('.' + styles['session-item'] + '.' + styles.active);
        expect(activeItem).toBeInTheDocument();
        expect(activeItem?.textContent).toContain('Session 1');
    });

    it('calls onSelectSession when session clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            data: { items: [fakeSessions[0]], total: 1, skip: 0, limit: 50 } as ChatSessionsReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
        const { props } = renderSidebar();
        await user.click(screen.getByText('Session 1'));
        expect(props.onSelectSession).toHaveBeenCalledWith(
            expect.objectContaining({ id: 's1' }),
        );
    });

    it('collapsed mode shows toggle and new-chat only', () => {
        renderSidebar({ collapsed: true });
        expect(document.querySelector('.' + styles['collapsed-sidebar'])).toBeInTheDocument();
        expect(screen.queryByText('历史记录')).not.toBeInTheDocument();
    });

    it('calls onNewChat when new-chat button clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        const { props } = renderSidebar();
        await user.click(screen.getByRole('button', { name: /新对话/ }));
        expect(props.onNewChat).toHaveBeenCalledOnce();
    });

    it('calls onToggle when toggle button clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        const { props } = renderSidebar();
        const toggleBtns = screen.getAllByRole('button');
        const toggleBtn = toggleBtns.find(
            (btn) => btn.classList.contains(styles['toggle-btn']),
        );
        expect(toggleBtn).toBeTruthy();
        await user.click(toggleBtn!);
        expect(props.onToggle).toHaveBeenCalledOnce();
    });

    it('updates the theme in store when theme button is clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });

        renderSidebar();

        const themeToggleBtn = screen.getByTestId('theme-toggle-btn');
        expect(themeToggleBtn).toBeInTheDocument();

        const { useThemeStore } = await import('../../stores/theme-store');
        const initialTheme = useThemeStore.getState().theme;

        await user.click(themeToggleBtn);

        const expectedTheme = initialTheme === 'dark' ? 'light' : 'dark';
        expect(useThemeStore.getState().theme).toBe(expectedTheme);
    });

    it('toggles language and translates UI elements correctly when language switch is clicked', async () => {
        const user = userEvent.setup();
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        
        renderSidebar();
        
        expect(screen.getByText('新对话')).toBeInTheDocument();
        
        const langBtn = screen.getByTestId('language-toggle-btn');
        await user.click(langBtn);
        
        expect(await screen.findByText('New Chat')).toBeInTheDocument();
        
        await user.click(langBtn);
        expect(await screen.findByText('新对话')).toBeInTheDocument();
    });

    it('localizes relative session timestamps after language switch', async () => {
        const user = userEvent.setup();
        vi.setSystemTime(new Date('2026-05-21T12:00:00.000Z'));
        mockUseAuth.mockReturnValue({ ...defaultAuth, isAuthenticated: true });
        mockUseChatSessionsQuery.mockReturnValue(makeQueryResult({
            data: {
                items: [{
                    ...fakeSessions[0],
                    updated_at: '2026-05-20T12:00:00.000Z',
                }],
                total: 1,
                skip: 0,
                limit: 50,
            } as ChatSessionsReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));

        renderSidebar();

        expect(screen.getByText('昨天')).toBeInTheDocument();

        const langBtn = screen.getByTestId('language-toggle-btn');
        await user.click(langBtn);

        expect(await screen.findByText('Yesterday')).toBeInTheDocument();
    });
});
