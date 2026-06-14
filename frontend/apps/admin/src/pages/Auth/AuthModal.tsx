import React from 'react';
import { Modal, Divider } from 'antd';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../context/useAuth';
import PhoneLoginForm from './PhoneLoginForm';
import GoogleLoginButton from './GoogleLoginButton';

const AuthModal: React.FC = () => {
    const { showAuthModal, setShowAuthModal } = useAuth();
    const { t } = useTranslation();

    const handleClose = () => {
        setShowAuthModal(false);
    };

    return (
        <Modal
            open={showAuthModal}
            onCancel={handleClose}
            footer={null}
            centered
            width={420}
            className="auth-modal"
            styles={{
                mask: {
                    backgroundColor: 'rgba(0, 0, 0, 0.45)',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                },
                body: {
                    padding: '24px',
                },
            }}
            style={{
                borderRadius: 16,
            }}
        >
            <div style={{ textAlign: 'center', marginBottom: 8 }}>
                <div style={{
                    fontSize: 28,
                    fontWeight: 700,
                    background: 'linear-gradient(135deg, var(--color-primary), var(--color-primary-gradient-end))',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    marginBottom: 4,
                }}>
                    {t('auth.title')}
                </div>
                <div style={{ color: '#999', fontSize: 14 }}>{t('auth.subtitle')}</div>
            </div>

            <PhoneLoginForm />

            <Divider style={{ margin: '20px 0', fontSize: 13, color: '#999' }}>
                {t('auth.or')}
            </Divider>

            <GoogleLoginButton />
        </Modal>
    );
};

export default AuthModal;
