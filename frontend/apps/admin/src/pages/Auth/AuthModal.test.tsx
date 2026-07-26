import { screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { API_URLS } from '../../api/urls';
import { server } from '../../test/msw/server';
import { renderWithQueryClient } from '../../test/render-with-query';
import AuthModal from './AuthModal';

vi.mock('../../context/useAuth', () => ({
    useAuth: () => ({
        showAuthModal: true,
        setShowAuthModal: vi.fn(),
    }),
}));

describe('AuthModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('shows password login when enable-password-login is true', async () => {
        server.use(
            http.get(API_URLS.AUTH.CONFIG, () =>
                HttpResponse.json({
                    'enable-password-login': true,
                }),
            ),
        );

        renderWithQueryClient(<AuthModal />);

        expect(await screen.findByText('内部账号登录')).toBeInTheDocument();
        expect(screen.getByPlaceholderText('请输入手机号')).toBeInTheDocument();
    });

    it('hides password login when enable-password-login is false', async () => {
        server.use(
            http.get(API_URLS.AUTH.CONFIG, () =>
                HttpResponse.json({
                    'enable-password-login': false,
                }),
            ),
        );

        renderWithQueryClient(<AuthModal />);

        await screen.findByPlaceholderText('请输入手机号');
        expect(screen.queryByText('内部账号登录')).not.toBeInTheDocument();
    });
});
