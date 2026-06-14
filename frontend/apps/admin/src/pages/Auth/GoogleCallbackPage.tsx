import React from 'react';
import { Spin, Result, Button } from 'antd';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { useAuth } from '../../context/useAuth';
import { googleCallbackAPI } from '../../api/auth';

const GoogleCallbackPage: React.FC = () => {
    const { login } = useAuth();
    const { t } = useTranslation();
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const [error, setError] = React.useState<string | null>(null);

    React.useEffect(() => {
        const code = searchParams.get('code');
        if (!code) {
            setError(t('auth.validation.code_required'));
            return;
        }

        const redirectUri = `${window.location.origin}/auth/google/callback`;
        googleCallbackAPI({ code, redirect_uri: redirectUri })
            .then(async (res) => {
                await login(res.access_token);
                navigate('/', { replace: true });
            })
            .catch((err) => {
                setError(err?.message ?? t('auth.google_login_failed'));
            });
    }, [searchParams, login, navigate]);

    if (error) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
                <Result
                    status="error"
                    title={error}
                    extra={
                        <Button type="primary" onClick={() => navigate('/')}>
                            {t('auth.sign_in')}
                        </Button>
                    }
                />
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}>
            <Spin size="large" tip={t('auth.authenticating')} />
        </div>
    );
};

export default GoogleCallbackPage;
