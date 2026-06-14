import React, { useEffect } from 'react';
import { Button, Form, Input, Modal } from 'antd';
import type { User } from '../../../types/user';
import type { UserFormValues } from './use-admin-users';

type EditUserModalProps = {
    open: boolean;
    editingUser: User | null;
    onSubmit: (values: UserFormValues) => Promise<void>;
    onCancel: () => void;
};

const EditUserModal: React.FC<EditUserModalProps> = ({ open, editingUser, onSubmit, onCancel }) => {
    const [form] = Form.useForm<UserFormValues>();

    useEffect(() => {
        if (open && editingUser) {
            form.setFieldsValue({
                username: editingUser.username,
                email: editingUser.email,
                is_active: editingUser.is_active,
                max_tokens: editingUser.max_tokens,
                password: undefined,
            });
        }
    }, [open, editingUser, form]);

    const handleSubmit = async (values: UserFormValues) => {
        await onSubmit(values);
        form.resetFields();
    };

    const handleCancel = () => {
        form.resetFields();
        onCancel();
    };

    return (
        <Modal
            title={`编辑用户: ${editingUser?.username}`}
            open={open}
            onCancel={handleCancel}
            footer={null}
        >
            <Form form={form} onFinish={handleSubmit} layout="vertical">
                <Form.Item name="username" label="用户名">
                    <Input placeholder="用户名" />
                </Form.Item>
                <Form.Item name="email" label="邮箱" rules={[{ type: 'email' }]}>
                    <Input placeholder="邮箱" />
                </Form.Item>
                <Form.Item name="password" label="新密码（留空不修改）">
                    <Input.Password placeholder="新密码" />
                </Form.Item>
                <Form.Item name="max_tokens" label="Token 上限">
                    <Input type="number" placeholder="Token 上限" />
                </Form.Item>
                <Form.Item>
                    <Button type="primary" htmlType="submit" block>更新</Button>
                </Form.Item>
            </Form>
        </Modal>
    );
};

export default EditUserModal;
