import React from 'react';
import { Modal, Tabs, Form, Input, Button, message } from 'antd';
import { User, Lock, Mail } from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { loginAPI, registerAPI } from '../../api/auth';
import type { LoginCredentials, UserRegistrationPayload } from '../../types/user';

type RegisterFormValues = Omit<UserRegistrationPayload, 'max_tokens'>;

const AuthModal: React.FC = () => {
    const { showAuthModal, setShowAuthModal, authTab, setAuthTab, login } = useAuth();
    const [loginLoading, setLoginLoading] = React.useState(false);
    const [registerLoading, setRegisterLoading] = React.useState(false);
    const [loginForm] = Form.useForm<LoginCredentials>();
    const [registerForm] = Form.useForm<RegisterFormValues>();

    const handleLogin = async (values: LoginCredentials) => {
        setLoginLoading(true);
        try {
            const res = await loginAPI(values);
            await login(res.access_token);
            message.success('登录成功');
            loginForm.resetFields();
        } catch {
            // 错误已在拦截器处理
        } finally {
            setLoginLoading(false);
        }
    };

    const handleRegister = async (values: RegisterFormValues) => {
        setRegisterLoading(true);
        try {
            await registerAPI(values);
            message.success('注册成功，请登录');
            registerForm.resetFields();
            setAuthTab('login');
        } catch (error) {
            console.error(error);
        } finally {
            setRegisterLoading(false);
        }
    };

    const handleClose = () => {
        setShowAuthModal(false);
        loginForm.resetFields();
        registerForm.resetFields();
    };

    const tabItems = [
        {
            key: 'login',
            label: '登录',
            children: (
                <Form form={loginForm} name="modal-login" onFinish={handleLogin} style={{ marginTop: 16 }}>
                    <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                        <Input
                            prefix={<User size={16} color="#999" />}
                            placeholder="用户名"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder="密码"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                        <Button type="primary" htmlType="submit" block size="large" loading={loginLoading}>
                            登录
                        </Button>
                    </Form.Item>
                </Form>
            ),
        },
        {
            key: 'register',
            label: '注册',
            children: (
                <Form form={registerForm} name="modal-register" onFinish={handleRegister} style={{ marginTop: 16 }}>
                    <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
                        <Input
                            prefix={<User size={16} color="#999" />}
                            placeholder="用户名"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item
                        name="email"
                        rules={[
                            { required: true, message: '请输入邮箱' },
                            { type: 'email', message: '请输入有效邮箱' },
                        ]}
                    >
                        <Input
                            prefix={<Mail size={16} color="#999" />}
                            placeholder="邮箱"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder="密码"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item
                        name="confirm_password"
                        dependencies={['password']}
                        rules={[
                            { required: true, message: '请再次输入密码' },
                            ({ getFieldValue }) => ({
                                validator(_, value) {
                                    if (!value || getFieldValue('password') === value) {
                                        return Promise.resolve();
                                    }
                                    return Promise.reject(new Error('两次输入的密码不一致'));
                                },
                            }),
                        ]}
                    >
                        <Input.Password
                            prefix={<Lock size={16} color="#999" />}
                            placeholder="确认密码"
                            size="large"
                        />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                        <Button type="primary" htmlType="submit" block size="large" loading={registerLoading}>
                            注册
                        </Button>
                    </Form.Item>
                </Form>
            ),
        },
    ];

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
                    background: 'linear-gradient(135deg, #1677ff, #722ed1)',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    marginBottom: 4,
                }}>
                    AI 助手
                </div>
                <div style={{ color: '#999', fontSize: 14 }}>登录以获得完整体验</div>
            </div>
            <Tabs
                activeKey={authTab}
                onChange={(key) => setAuthTab(key as 'login' | 'register')}
                items={tabItems}
                centered
            />
        </Modal>
    );
};

export default AuthModal;
