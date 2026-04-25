import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockUseAuth = vi.fn();

vi.mock('./pages/Chat', () => ({
    default: () => <div>chat-page</div>,
}));

vi.mock('./pages/Admin', () => ({
    default: () => <div>admin-dashboard</div>,
}));

vi.mock('./context/AuthContext', () => ({
    AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('./context/useAuth', () => ({
    useAuth: () => mockUseAuth(),
}));

import App from './App';

describe('App routing', () => {
    beforeEach(() => {
        mockUseAuth.mockReturnValue({
            isAuthenticated: false,
            isLoading: false,
            user: null,
            setShowAuthModal: vi.fn(),
        });
    });

    it('renders the chat page on the root route', () => {
        window.history.pushState({}, '', '/');

        render(<App />);

        expect(screen.getByText('chat-page')).toBeInTheDocument();
    });

    it('loads the admin page for authenticated superusers', async () => {
        mockUseAuth.mockReturnValue({
            isAuthenticated: true,
            isLoading: false,
            user: { is_superuser: true },
            setShowAuthModal: vi.fn(),
        });
        window.history.pushState({}, '', '/admin');

        render(<App />);

        expect(await screen.findByText('admin-dashboard')).toBeInTheDocument();
    });
});
