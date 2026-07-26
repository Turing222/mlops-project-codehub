import React from 'react';
import { Shield, Users } from 'lucide-react';
import { useAdminUsers } from '../../features/admin/users/use-admin-users';
import UserSearchBar from '../../features/admin/users/UserSearchBar';
import UserTable from '../../features/admin/users/UserTable';
import CreateUserModal from '../../features/admin/users/CreateUserModal';
import EditUserModal from '../../features/admin/users/EditUserModal';
import AppShell from '../../components/shell/AppShell';
import Container from '../../components/shell/Container';
import PageHeader from '../../components/shell/PageHeader';
import styles from './AdminDashboard.module.css';

const AdminDashboard: React.FC = () => {
    const admin = useAdminUsers();

    return (
        <AppShell
            pageTitle="管理后台"
            pageIcon={<Shield size={18} color="var(--color-primary)" />}
            rootClassName={`${styles['admin-layout']} admin-layout`}
        >
            <Container variant="admin">
                <div className={styles['content-card']}>
                    <PageHeader
                        title="用户管理"
                        icon={<Users size={20} />}
                        actions={
                            <UserSearchBar
                                searchValue={admin.searchValue}
                                onSearchValueChange={admin.setSearchValue}
                                onSearch={admin.handleSearch}
                                onCreateClick={() => admin.setCreateModalOpen(true)}
                                onUpload={admin.handleUpload}
                            />
                        }
                    />
                    <UserTable
                        users={admin.users}
                        loading={admin.loading}
                        onEdit={admin.handleEdit}
                        onDeactivate={admin.handleDeactivate}
                    />
                </div>
            </Container>

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
        </AppShell>
    );
};

export default AdminDashboard;
