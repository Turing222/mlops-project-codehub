import React from 'react';
import { Form, Input, Button, message } from 'antd';
import { Phone, KeyRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { useAuth } from '../../context/useAuth';
import { sendSMSCodeAPI, smsLoginAPI } from '../../api/auth';

const COUNTDOWN_SECONDS = 60;

const PhoneLoginForm: React.FC = () => {
    const { login } = useAuth();
    const { t } = useTranslation();
    const [form] = Form.useForm();
    const [loading, setLoading] = React.useState(false);
    const [codeSent, setCodeSent] = React.useState(false);
    const [countdown, setCountdown] = React.useState(0);
    const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

    React.useEffect(() => {
        return () => {
            if (timerRef.current) clearInterval(timerRef.current);
        };
    }, []);

    const startCountdown = () => {
        setCountdown(COUNTDOWN_SECONDS);
        timerRef.current = setInterval(() => {
            setCountdown((prev) => {
                if (prev <= 1) {
                    if (timerRef.current) clearInterval(timerRef.current);
                    return 0;
                }
                return prev - 1;
            });
        }, 1000);
    };

    const handleSendCode = async () => {
        try {
            const phone = form.getFieldValue('phone');
            if (!phone || !/^\+?\d{7,15}$/.test(phone)) {
                form.validateFields(['phone']);
                return;
            }
            await sendSMSCodeAPI(phone);
            setCodeSent(true);
            startCountdown();
            message.success(t('auth.code_sent'));
        } catch {
            // error handled by interceptor
        }
    };

    const handleSubmit = async (values: { phone: string; code: string }) => {
        setLoading(true);
        try {
            const res = await smsLoginAPI({ phone: values.phone, code: values.code });
            await login(res.access_token);
            message.success(t('auth.login_success'));
            form.resetFields();
            setCodeSent(false);
        } catch {
            // error handled by interceptor
        } finally {
            setLoading(false);
        }
    };

    return (
        <Form form={form} name="phone-login" onFinish={handleSubmit} style={{ marginTop: 16 }}>
            <Form.Item
                name="phone"
                rules={[
                    { required: true, message: t('auth.validation.phone_required') },
                    { pattern: /^\+?\d{7,15}$/, message: t('auth.validation.phone_invalid') },
                ]}
            >
                <Input
                    prefix={<Phone size={16} color="#999" />}
                    placeholder={t('auth.phone_placeholder')}
                    size="large"
                />
            </Form.Item>

            <Form.Item>
                <div style={{ display: 'flex', gap: 8 }}>
                    <Form.Item
                        name="code"
                        noStyle
                        rules={[
                            { required: true, message: t('auth.validation.code_required') },
                            { len: 6, message: t('auth.validation.code_invalid') },
                        ]}
                    >
                        <Input
                            prefix={<KeyRound size={16} color="#999" />}
                            placeholder={t('auth.code_placeholder')}
                            size="large"
                            maxLength={6}
                            style={{ flex: 1 }}
                        />
                    </Form.Item>
                    <Button
                        size="large"
                        onClick={handleSendCode}
                        disabled={countdown > 0}
                        style={{ minWidth: 120 }}
                    >
                        {countdown > 0
                            ? `${countdown}s ${t('auth.resend_code')}`
                            : codeSent
                              ? t('auth.resend_code')
                              : t('auth.send_code')}
                    </Button>
                </div>
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
                <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                    {t('auth.sign_in')}
                </Button>
            </Form.Item>
        </Form>
    );
};

export default PhoneLoginForm;
