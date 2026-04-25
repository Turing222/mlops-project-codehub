import React, { useState } from 'react';
import {
    Avatar,
    Button,
    Form,
    Input,
    Layout,
    message,
    Modal,
    Popconfirm,
    Space,
    Table,
    Tag,
    Tooltip,
    Upload,
} from 'antd';
import type { TableColumnsType } from 'antd';
import { Users, ArrowLeft, Search, UserPlus, Upload as UploadIcon, Edit, Trash2, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import { queryUserAPI, updateUserAPI, registerUserAPI, uploadUsersCSVAPI } from '../../api/users';
import type {
    User,
    UserImportResponse,
    UserRegistrationPayload,
    UserUpdatePayload,
} from '../../types/user';
import './AdminDashboard.css';

const { Header, Content } = Layout;

type UserFormValues = {
    username?: string;
    email?: string;
    password?: string;
    max_tokens?: number | string;
    is_active?: boolean;
};

type CreateUserFormValues = Required<Pick<UserFormValues, 'username' | 'email' | 'password'>> &
    Pick<UserFormValues, 'max_tokens'>;

const AdminDashboard: React.FC = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(false);
    const [searchValue, setSearchValue] = useState('');
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [editingUser, setEditingUser] = useState<User | null>(null);
    const [createForm] = Form.useForm<CreateUserFormValues>();
    const [editForm] = Form.useForm<UserFormValues>();

    const handleSearch = async () => {
        if (!searchValue.trim()) {
            message.warning('请输入用户名或邮箱');
            return;
        }
        setLoading(true);
        try {
            const isEmail = searchValue.includes('@');
            const res = await queryUserAPI(
                isEmail ? { email: searchValue } : { username: searchValue }
            );
            setUsers(res ? [res] : []);
            if (!res) message.info('未找到用户');
        } catch {
            setUsers([]);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async (values: CreateUserFormValues) => {
        try {
            const payload: UserRegistrationPayload = {
                ...values,
                confirm_password: values.password,
                max_tokens: values.max_tokens !== undefined ? Number(values.max_tokens) : undefined,
            };
            await registerUserAPI(payload);
            message.success('用户创建成功');
            setCreateModalOpen(false);
            createForm.resetFields();
        } catch {
            // handled
        }
    };

    const handleEdit = (record: User) => {
        setEditingUser(record);
        editForm.setFieldsValue({
            username: record.username,
            email: record.email,
            is_active: record.is_active,
            max_tokens: record.max_tokens,
        });
        setEditModalOpen(true);
    };

    const handleUpdate = async (values: UserFormValues) => {
        if (!editingUser) return;
        try {
            const updateData: UserUpdatePayload = {};
            if (values.username) updateData.username = values.username;
            if (values.email) updateData.email = values.email;
            if (values.password) updateData.password = values.password;
            if (values.max_tokens !== undefined) updateData.max_tokens = Number(values.max_tokens);
            if (values.is_active !== undefined) updateData.is_active = values.is_active;

            const updated = await updateUserAPI(editingUser.id, updateData);
            setUsers((prev) => prev.map((u) => (u.id === editingUser.id ? updated : u)));
            message.success('用户更新成功');
            setEditModalOpen(false);
            editForm.resetFields();
        } catch {
            // handled
        }
    };

    const handleDeactivate = async (record: User) => {
        try {
            const updated = await updateUserAPI(record.id, { is_active: false });
            setUsers((prev) => prev.map((u) => (u.id === record.id ? updated : u)));
            message.success('用户已停用');
        } catch {
            // handled
        }
    };

    const handleUpload = async (file: File) => {
        try {
            const res: UserImportResponse = await uploadUsersCSVAPI(file);
            message.success(res?.message || '批量导入成功');
        } catch {
            // handled
        }
        return false;
    };

    const columns: TableColumnsType<User> = [
        {
            title: '用户',
            dataIndex: 'username',
            key: 'username',
            render: (text: string) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Avatar style={{ background: 'linear-gradient(135deg, #1677ff, #722ed1)' }} size={32}>
                        {text?.[0]?.toUpperCase()}
                    </Avatar>
                    <span>{text}</span>
                </div>
            ),
        },
        {
            title: '邮箱',
            dataIndex: 'email',
            key: 'email',
        },
        {
            title: '状态',
            dataIndex: 'is_active',
            key: 'is_active',
            render: (active: boolean) => (
                <Tag color={active ? 'green' : 'red'}>{active ? '活跃' : '已停用'}</Tag>
            ),
        },
        {
            title: '角色',
            dataIndex: 'is_superuser',
            key: 'is_superuser',
            render: (su: boolean) => (
                <Tag color={su ? 'purple' : 'default'}>{su ? '超级管理员' : '普通用户'}</Tag>
            ),
        },
        {
            title: 'Token 消耗',
            key: 'tokens',
            render: (_value: unknown, record: User) => {
                const used = record.used_tokens || 0;
                const max = record.max_tokens || 0;
                const percent = max > 0 ? Math.min(100, (used / max) * 100) : 0;
                let color = 'blue';
                if (percent > 90) color = 'red';
                else if (percent > 70) color = 'orange';

                return (
                    <div style={{ width: 150 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                            <span>{used} / {max}</span>
                            <span>{Math.round(percent)}%</span>
                        </div>
                        <div style={{
                            height: 6,
                            background: '#f0f0f0',
                            borderRadius: 3,
                            overflow: 'hidden'
                        }}>
                            <div style={{
                                width: `${percent}%`,
                                height: '100%',
                                background: color === 'red' ? '#ff4d4f' : color === 'orange' ? '#faad14' : '#1677ff',
                                borderRadius: 3,
                                transition: 'all 0.3s'
                            }} />
                        </div>
                    </div>
                );
            },
        },
        {
            title: '创建时间',
            dataIndex: 'created_at',
            key: 'created_at',
            render: (t: string) => t ? new Date(t).toLocaleDateString('zh-CN') : '-',
        },
        {
            title: '操作',
            key: 'action',
            render: (_value: unknown, record: User) => (
                <Space>
                    <Tooltip title="编辑">
                        <Button type="text" icon={<Edit size={14} />} onClick={() => handleEdit(record)} />
                    </Tooltip>
                    <Popconfirm title="确定停用该用户？" onConfirm={() => handleDeactivate(record)}>
                        <Tooltip title="停用">
                            <Button type="text" danger icon={<Trash2 size={14} />} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    return (
        <Layout className="admin-layout">
            <Header className="admin-header">
                <div className="header-left">
                    <Button
                        type="text"
                        icon={<ArrowLeft size={18} />}
                        onClick={() => navigate('/')}
                        style={{ color: '#fff', marginRight: 12 }}
                    />
                    <Shield size={22} color="#1677ff" />
                    <span className="header-title">管理后台</span>
                </div>
                <div className="header-right">
                    <span className="header-user">{user?.username}</span>
                </div>
            </Header>
            <Content className="admin-content">
                <div className="content-card">
                    <div className="card-header">
                        <h2><Users size={20} /> 用户管理</h2>
                        <Space>
                            <Input.Search
                                placeholder="搜索用户名或邮箱"
                                value={searchValue}
                                onChange={(e) => setSearchValue(e.target.value)}
                                onSearch={handleSearch}
                                enterButton={<Search size={14} />}
                                style={{ width: 280 }}
                                allowClear
                            />
                            <Button
                                type="primary"
                                icon={<UserPlus size={14} />}
                                onClick={() => setCreateModalOpen(true)}
                            >
                                新建用户
                            </Button>
                            <Upload showUploadList={false} beforeUpload={handleUpload} accept=".csv,.xlsx,.xls">
                                <Button icon={<UploadIcon size={14} />}>批量导入</Button>
                            </Upload>
                        </Space>
                    </div>
                    <Table
                        columns={columns}
                        dataSource={users}
                        rowKey="id"
                        loading={loading}
                        pagination={false}
                        locale={{ emptyText: '搜索用户以查看结果' }}
                    />
                </div>
            </Content>

            {/* 新建用户 */}
            <Modal
                title="新建用户"
                open={createModalOpen}
                onCancel={() => { setCreateModalOpen(false); createForm.resetFields(); }}
                footer={null}
            >
                <Form form={createForm} onFinish={handleCreate} layout="vertical">
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

            {/* 编辑用户 */}
            <Modal
                title={`编辑用户: ${editingUser?.username}`}
                open={editModalOpen}
                onCancel={() => { setEditModalOpen(false); editForm.resetFields(); }}
                footer={null}
            >
                <Form form={editForm} onFinish={handleUpdate} layout="vertical">
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
        </Layout>
    );
};

export default AdminDashboard;
