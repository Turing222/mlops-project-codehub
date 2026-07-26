import React from 'react';
import { Form, Input, Button } from 'antd';
import { KeyRound, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import {
    usePasswordLogin,
    type PasswordLoginFormValues,
} from './use-password-login';

const PasswordLoginForm: React.FC = () => {
    const { t } = useTranslation();
    const [form] = Form.useForm<PasswordLoginFormValues>();
    const { mutateAsync, isPending } = usePasswordLogin();

    const handleSubmit = async (values: PasswordLoginFormValues) => {
        try {
            await mutateAsync(values);
            form.resetFields();
        } catch {
            // error handled by interceptor
        }
    };

    return (
        <Form form={form} name="password-login" onFinish={handleSubmit}>
            <Form.Item
                name="username"
                rules={[{ required: true, message: t('auth.validation.username_required') }]}
            >
                <Input
                    prefix={<UserRound size={16} color="#999" />}
                    placeholder={t('auth.username')}
                    size="large"
                    autoComplete="username"
                    data-testid="password-login-username"
                />
            </Form.Item>

            <Form.Item
                name="password"
                rules={[{ required: true, message: t('auth.validation.password_required') }]}
            >
                <Input.Password
                    prefix={<KeyRound size={16} color="#999" />}
                    placeholder={t('auth.password')}
                    size="large"
                    autoComplete="current-password"
                    data-testid="password-login-password"
                />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
                <Button
                    type="primary"
                    htmlType="submit"
                    block
                    size="large"
                    loading={isPending}
                    data-testid="password-login-submit"
                >
                    {t('auth.staff_sign_in')}
                </Button>
            </Form.Item>
        </Form>
    );
};

export default PasswordLoginForm;
