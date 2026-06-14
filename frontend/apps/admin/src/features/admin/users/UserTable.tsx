import React from 'react';
import { Avatar, Button, Popconfirm, Space, Table, Tag, Tooltip } from 'antd';
import type { TableColumnsType } from 'antd';
import { Edit, Trash2, Search } from 'lucide-react';
import type { User } from '../../../types/user';
import styles from './UserTable.module.css';

type UserTableProps = {
    users: User[];
    loading: boolean;
    onEdit: (record: User) => void;
    onDeactivate: (record: User) => Promise<void>;
};

const UserTable: React.FC<UserTableProps> = ({ users, loading, onEdit, onDeactivate }) => {
    const columns: TableColumnsType<User> = [
        {
            title: '用户',
            dataIndex: 'username',
            key: 'username',
            width: 160,
            render: (text: string) => (
                <div className={styles['user-cell']}>
                    <Avatar className={styles['user-cell-avatar']} size={32}>
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
            width: 100,
            render: (active: boolean) => (
                <Tag color={active ? 'green' : 'red'}>{active ? '活跃' : '已停用'}</Tag>
            ),
        },
        {
            title: '角色',
            dataIndex: 'is_superuser',
            key: 'is_superuser',
            width: 120,
            render: (su: boolean) => (
                <Tag color={su ? 'purple' : 'default'}>{su ? '超级管理员' : '普通用户'}</Tag>
            ),
        },
        {
            title: 'Token 消耗',
            key: 'tokens',
            width: 220,
            render: (_value: unknown, record: User) => {
                const used = record.used_tokens || 0;
                const max = record.max_tokens || 0;
                const percent = max > 0 ? Math.min(100, (used / max) * 100) : 0;
                let level = 'low';
                if (percent > 90) level = 'high';
                else if (percent > 70) level = 'mid';

                return (
                    <div className={styles['token-compact-row']}>
                        <span className={styles['token-digits']}>{used}/{max}</span>
                        <div className={styles['mini-progress-track']}>
                            <div
                                className={`${styles['mini-progress-fill']} ${styles[`level-${level}`]}`}
                                style={{ width: `${percent}%` }}
                            />
                        </div>
                        <span className={styles['token-percent-label']}>{Math.round(percent)}%</span>
                    </div>
                );
            },
        },
        {
            title: '创建时间',
            dataIndex: 'created_at',
            key: 'created_at',
            width: 120,
            render: (t: string) => t ? new Date(t).toLocaleDateString('zh-CN') : '-',
        },
        {
            title: '操作',
            key: 'action',
            width: 100,
            align: 'center',
            render: (_value: unknown, record: User) => (
                <Space>
                    <Tooltip title="编辑">
                        <Button type="text" icon={<Edit size={14} />} onClick={() => onEdit(record)} />
                    </Tooltip>
                    <Popconfirm title="确定停用该用户？" onConfirm={() => onDeactivate(record)}>
                        <Tooltip title="停用">
                            <Button type="text" danger icon={<Trash2 size={14} />} />
                        </Tooltip>
                    </Popconfirm>
                </Space>
            ),
        },
    ];

    return (
        <Table
            columns={columns}
            dataSource={users}
            rowKey="id"
            loading={loading}
            pagination={false}
            locale={{
                emptyText: (
                    <div className={styles['user-table-empty']}>
                        <Search size={32} className={styles['user-table-empty-icon']} />
                        <div className={styles['user-table-empty-text']}>搜索用户以查看结果</div>
                    </div>
                ),
            }}
        />
    );
};

export default UserTable;
