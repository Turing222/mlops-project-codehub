import React from 'react';
import { Button, Layout } from 'antd';
import { ArrowLeft, Shield, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/useAuth';
import { useAdminUsers } from '../../features/admin/users/use-admin-users';
import UserSearchBar from '../../features/admin/users/UserSearchBar';
import UserTable from '../../features/admin/users/UserTable';
import CreateUserModal from '../../features/admin/users/CreateUserModal';
import EditUserModal from '../../features/admin/users/EditUserModal';
import styles from './AdminDashboard.module.css';

const { Header, Content } = Layout;

const AdminDashboard: React.FC = () => {
    const { user } = useAuth();
    const navigate = useNavigate();
    const admin = useAdminUsers();

    return (
        <Layout className={`${styles['admin-layout']} admin-layout`}>
            <Header className={styles['admin-header']}>
                <div className={styles['header-left']}>
                    <Button
                        type="text"
                        icon={<ArrowLeft size={18} />}
                        onClick={() => navigate('/')}
                        className={styles['back-btn']}
                    />
                    <Shield size={22} color="#1677ff" />
                    <span className={`${styles['header-title']} header-title`}>管理后台</span>
                </div>
                <div className={styles['header-right']}>
                    <span className={styles['header-user']}>{user?.username}</span>
                </div>
            </Header>
            <Content className={styles['admin-content']}>
                <div className={styles['content-card']}>
                    <div className={styles['card-header']}>
                        <h2><Users size={20} /> 用户管理</h2>
                        <UserSearchBar
                            searchValue={admin.searchValue}
                            onSearchValueChange={admin.setSearchValue}
                            onSearch={admin.handleSearch}
                            onCreateClick={() => admin.setCreateModalOpen(true)}
                            onUpload={admin.handleUpload}
                        />
                    </div>
                    <UserTable
                        users={admin.users}
                        loading={admin.loading}
                        onEdit={admin.handleEdit}
                        onDeactivate={admin.handleDeactivate}
                    />
                </div>
            </Content>

            <CreateUserModal
                open={admin.createModalOpen}
                onSubmit={admin.handleCreate}
                onCancel={admin.closeCreateModal}
            />

            <EditUserModal
                open={admin.editModalOpen}
                editingUser={admin.editingUser}
                onSubmit={admin.handleUpdate}
                onCancel={admin.closeEditModal}
            />
        </Layout>
    );
};

export default AdminDashboard;
