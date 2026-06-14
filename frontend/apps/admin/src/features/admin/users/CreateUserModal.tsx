import React from 'react';
import { Button, Form, Input, Modal } from 'antd';
import type { CreateUserFormValues } from './use-admin-users';

type CreateUserModalProps = {
    open: boolean;
    onSubmit: (values: CreateUserFormValues) => Promise<void>;
    onCancel: () => void;
};

const CreateUserModal: React.FC<CreateUserModalProps> = ({ open, onSubmit, onCancel }) => {
    const [form] = Form.useForm<CreateUserFormValues>();

    const handleSubmit = async (values: CreateUserFormValues) => {
        await onSubmit(values);
        form.resetFields();
    };

    const handleCancel = () => {
        form.resetFields();
        onCancel();
    };

    return (
        <Modal
            title="新建用户"
            open={open}
            onCancel={handleCancel}
            footer={null}
        >
            <Form form={form} onFinish={handleSubmit} layout="vertical">
                <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                    <Input placeholder="用户名" />
                </Form.Item>
                <Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}>
                    <Input placeholder="邮箱" />
                </Form.Item>
                <Form.Item name="password" label="密码" rules={[{ required: true, min: 8 }]}>
                    <Input.Password placeholder="密码（至少8位）" />
                </Form.Item>
                <Form.Item name="max_tokens" label="Token 上限" initialValue={100000}>
                    <Input type="number" placeholder="Token 上限" />
                </Form.Item>
                <Form.Item>
                    <Button type="primary" htmlType="submit" block>创建</Button>
                </Form.Item>
            </Form>
        </Modal>
    );
};

export default CreateUserModal;
