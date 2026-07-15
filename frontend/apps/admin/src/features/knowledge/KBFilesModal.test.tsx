import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClientProvider } from '@tanstack/react-query';
import { message } from 'antd';
import type { ReactNode } from 'react';
import KBFilesModal from './KBFilesModal';
import { createTestQueryClient } from '../../test/render-with-query';
import { knowledgeKeys } from '../../query/keys/knowledge';
import { useAuthStore } from '../../stores/auth-store';

vi.mock('../../api/knowledge', () => ({
    getDefaultKBFilesAPI: vi.fn(),
    deleteKBFileAPI: vi.fn(),
}));

vi.mock('../../query/hooks/auth', () => ({
    useMeQuery: vi.fn(),
}));

vi.mock('../../context/useAuth', () => ({
    useAuth: vi.fn(),
}));

import { deleteKBFileAPI, getDefaultKBFilesAPI } from '../../api/knowledge';
import { useMeQuery } from '../../query/hooks/auth';
import { useAuth } from '../../context/useAuth';

const mockGetDefaultKBFilesAPI = vi.mocked(getDefaultKBFilesAPI);
const mockDeleteKBFileAPI = vi.mocked(deleteKBFileAPI);
const mockUseMeQuery = vi.mocked(useMeQuery);
const mockUseAuth = vi.mocked(useAuth);

const files = [
    {
        id: 'f1',
        kb_id: 'kb1',
        filename: 'guide.md',
        file_size: 2048,
        status: 'READY',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    },
];

const filesV2 = [
    {
        ...files[0],
        id: 'f2',
        filename: 'guide-v2.md',
    },
];

type MeQueryReturn = ReturnType<typeof useMeQuery>;

function mockMe(overrides: Partial<MeQueryReturn> = {}): MeQueryReturn {
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
    } as MeQueryReturn;
}

function setAuth(isAuthenticated: boolean) {
    mockUseAuth.mockReturnValue({
        user: isAuthenticated ? { id: '1', username: 'alice' } as never : null,
        token: isAuthenticated ? 'tok' : null,
        isLoading: false,
        login: vi.fn(),
        logout: vi.fn(),
        isAuthenticated,
        showAuthModal: false,
        setShowAuthModal: vi.fn(),
        refreshUser: vi.fn(),
    });
    if (isAuthenticated) {
        useAuthStore.getState().setToken('tok');
        mockUseMeQuery.mockReturnValue(mockMe({
            data: { id: '1', username: 'alice' } as MeQueryReturn['data'],
            isSuccess: true,
            isPending: false,
            status: 'success',
        }));
    } else {
        useAuthStore.getState().clearAuth();
        mockUseMeQuery.mockReturnValue(mockMe({
            data: undefined,
            isSuccess: false,
            isPending: true,
            status: 'pending',
        }));
    }
}

function renderModal(
    visible: boolean,
    queryClient = createTestQueryClient(),
) {
    const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return {
        queryClient,
        ...render(
            <KBFilesModal visible={visible} onClose={vi.fn()} />,
            { wrapper },
        ),
    };
}

beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.getState().resetAll();
    setAuth(true);
    mockGetDefaultKBFilesAPI.mockResolvedValue(files);
    mockDeleteKBFileAPI.mockResolvedValue(undefined);
});

describe('KBFilesModal', () => {
    it('does not load files while closed', () => {
        renderModal(false);
        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });

    it('does not request when modal is open but user is logged out', () => {
        setAuth(false);
        renderModal(true);
        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });

    it('stops requesting after logout while modal stays visible', async () => {
        const { rerender, queryClient } = renderModal(true);

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });

        mockGetDefaultKBFilesAPI.mockClear();
        setAuth(false);
        rerender(
            <QueryClientProvider client={queryClient}>
                <KBFilesModal visible onClose={vi.fn()} />
            </QueryClientProvider>,
        );

        expect(mockGetDefaultKBFilesAPI).not.toHaveBeenCalled();
    });

    it('shows loading then file data when opened', async () => {
        let resolveFiles: (value: typeof files) => void = () => undefined;
        mockGetDefaultKBFilesAPI.mockImplementation(
            () => new Promise((resolve) => {
                resolveFiles = resolve;
            }),
        );

        renderModal(true);

        expect(document.querySelector('.ant-spin')).toBeTruthy();

        await act(async () => {
            resolveFiles(files);
        });

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });
    });

    it('refreshes file list when closed and reopened', async () => {
        const queryClient = createTestQueryClient();
        const { rerender } = renderModal(true, queryClient);

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });
        expect(mockGetDefaultKBFilesAPI).toHaveBeenCalledTimes(1);

        rerender(
            <QueryClientProvider client={queryClient}>
                <KBFilesModal visible={false} onClose={vi.fn()} />
            </QueryClientProvider>,
        );

        mockGetDefaultKBFilesAPI.mockResolvedValueOnce(filesV2);
        rerender(
            <QueryClientProvider client={queryClient}>
                <KBFilesModal visible onClose={vi.fn()} />
            </QueryClientProvider>,
        );

        await waitFor(() => {
            expect(mockGetDefaultKBFilesAPI).toHaveBeenCalledTimes(2);
            expect(screen.getByText('guide-v2.md')).toBeInTheDocument();
        });
    });

    it('toasts load failure once for the same errorUpdatedAt', async () => {
        const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);
        mockGetDefaultKBFilesAPI.mockRejectedValue(new Error('network'));

        const { rerender, queryClient } = renderModal(true);

        await waitFor(() => {
            expect(errorSpy).toHaveBeenCalled();
        });
        const firstCallCount = errorSpy.mock.calls.length;

        rerender(
            <QueryClientProvider client={queryClient}>
                <KBFilesModal visible onClose={vi.fn()} />
            </QueryClientProvider>,
        );

        expect(errorSpy.mock.calls.length).toBe(firstCallCount);
        errorSpy.mockRestore();
    });

    it('keeps previous successful data when a later load fails', async () => {
        const queryClient = createTestQueryClient();
        queryClient.setQueryData(knowledgeKeys.files(), files);
        mockGetDefaultKBFilesAPI.mockRejectedValue(new Error('network'));
        vi.spyOn(message, 'error').mockImplementation(() => undefined as never);

        renderModal(true, queryClient);

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });
        expect(queryClient.getQueryData(knowledgeKeys.files())).toEqual(files);
    });

    it('shows success toast after delete', async () => {
        const user = userEvent.setup();
        const successSpy = vi.spyOn(message, 'success').mockImplementation(() => undefined as never);

        renderModal(true);

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });

        const row = screen.getByText('guide.md').closest('tr');
        expect(row).toBeTruthy();
        const actionButton = row!.querySelector('button');
        expect(actionButton).toBeTruthy();
        await user.click(actionButton!);

        await waitFor(() => {
            expect(document.querySelector('.ant-popconfirm')).toBeTruthy();
        });
        const confirmBtn = document.querySelector(
            '.ant-popconfirm-buttons .ant-btn-primary, .ant-popconfirm .ant-btn-primary',
        ) as HTMLButtonElement | null;
        expect(confirmBtn).toBeTruthy();
        await user.click(confirmBtn!);

        await waitFor(() => {
            expect(mockDeleteKBFileAPI).toHaveBeenCalledWith('f1');
            expect(successSpy).toHaveBeenCalled();
        });
        successSpy.mockRestore();
    });

    it('keeps list and shows failure toast when delete fails', async () => {
        const user = userEvent.setup();
        mockDeleteKBFileAPI.mockRejectedValue(new Error('delete failed'));
        const errorSpy = vi.spyOn(message, 'error').mockImplementation(() => undefined as never);

        renderModal(true);

        await waitFor(() => {
            expect(screen.getByText('guide.md')).toBeInTheDocument();
        });

        const row = screen.getByText('guide.md').closest('tr');
        const actionButton = row!.querySelector('button');
        await user.click(actionButton!);

        await waitFor(() => {
            expect(document.querySelector('.ant-popconfirm')).toBeTruthy();
        });
        const confirmBtn = document.querySelector(
            '.ant-popconfirm-buttons .ant-btn-primary, .ant-popconfirm .ant-btn-primary',
        ) as HTMLButtonElement | null;
        await user.click(confirmBtn!);

        await waitFor(() => {
            expect(errorSpy).toHaveBeenCalled();
        });
        expect(screen.getByText('guide.md')).toBeInTheDocument();
        errorSpy.mockRestore();
    });
});
