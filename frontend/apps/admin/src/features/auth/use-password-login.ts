import { useMutation } from '@tanstack/react-query';
import { message } from 'antd';
import { useTranslation } from 'react-i18next';

import { loginAPI } from '../../api/auth';
import { useAuth } from '../../context/useAuth';
import type { LoginCredentials } from '../../schemas/auth';

export type PasswordLoginFormValues = LoginCredentials;

export function usePasswordLogin() {
    const { login } = useAuth();
    const { t } = useTranslation();

    return useMutation({
        mutationFn: loginAPI,
        onSuccess: async (authResponse) => {
            await login(authResponse.access_token);
            message.success(t('auth.login_success'));
        },
    });
}
