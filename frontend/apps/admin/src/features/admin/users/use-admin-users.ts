import { useState, useCallback } from 'react';
import { message } from 'antd';
import { useUserSearchQuery, useUpdateUserMutation, useRegisterUserMutation, useUploadUsersCSVMutation, createIdempotencyKey } from '../../../query/hooks/users';
import type { User, UserRegistrationPayload, UserUpdatePayload } from '../../../types/user';

export type UserFormValues = {
    username?: string | null;
    email?: string | null;
    password?: string;
    max_tokens?: number | string | null;
    is_active?: boolean | null;
};

export type CreateUserFormValues = {
    username: string;
    email: string;
    password: string;
    max_tokens?: number | string | null;
};

type SearchParams = { username?: string; email?: string } | null;

export type UseAdminUsersReturn = {
    users: User[];
    loading: boolean;
    searchValue: string;
    setSearchValue: (v: string) => void;
    createModalOpen: boolean;
    setCreateModalOpen: (v: boolean) => void;
    editModalOpen: boolean;
    editingUser: User | null;
    handleSearch: () => void;
    handleCreate: (values: CreateUserFormValues) => Promise<void>;
    handleEdit: (record: User) => void;
    handleUpdate: (values: UserFormValues) => Promise<void>;
    handleDeactivate: (record: User) => Promise<void>;
    handleUpload: (file: File) => Promise<boolean>;
    closeCreateModal: () => void;
    closeEditModal: () => void;
};

export function useAdminUsers(): UseAdminUsersReturn {
    const [searchValue, setSearchValue] = useState('');
    const [searchParams, setSearchParams] = useState<SearchParams>(null);
    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [editingUser, setEditingUser] = useState<User | null>(null);

    const { data: searchData, isLoading: searchLoading } = useUserSearchQuery(searchParams || { username: '', email: '' });
    const updateUserMutation = useUpdateUserMutation();
    const registerUserMutation = useRegisterUserMutation();
    const uploadCSVMutation = useUploadUsersCSVMutation();

    const users: User[] = searchParams ? (searchData ? [searchData] : []) : [];

    const handleSearch = useCallback(() => {
        if (!searchValue.trim()) {
            message.warning('请输入用户名或邮箱');
            return;
        }
        const isEmail = searchValue.includes('@');
        const params = isEmail ? { email: searchValue } : { username: searchValue };
        setSearchParams(params);
    }, [searchValue]);

    const handleCreate = useCallback(async (values: CreateUserFormValues) => {
        const payload: UserRegistrationPayload = {
            ...values,
            confirm_password: values.password,
            max_tokens: values.max_tokens !== undefined ? Number(values.max_tokens) : undefined,
        };
        await registerUserMutation.mutateAsync(payload);
        message.success('用户创建成功');
        setCreateModalOpen(false);
    }, [registerUserMutation]);

    const handleEdit = useCallback((record: User) => {
        setEditingUser(record);
        setEditModalOpen(true);
    }, []);

    const handleUpdate = useCallback(async (values: UserFormValues) => {
        if (!editingUser) return;
        const updateData: UserUpdatePayload = {};
        if (values.username) updateData.username = values.username;
        if (values.email) updateData.email = values.email;
        if (values.password) updateData.password = values.password;
        if (values.max_tokens !== undefined && values.max_tokens !== null) updateData.max_tokens = Number(values.max_tokens);
        if (values.is_active !== undefined && values.is_active !== null) updateData.is_active = values.is_active;

        await updateUserMutation.mutateAsync({ id: editingUser.id, data: updateData });
        message.success('用户更新成功');
        setEditModalOpen(false);
    }, [editingUser, updateUserMutation]);

    const handleDeactivate = useCallback(async (record: User) => {
        try {
            await updateUserMutation.mutateAsync({ id: record.id, data: { is_active: false } });
            message.success('用户已停用');
        } catch {
            // handled by HTTP client
        }
    }, [updateUserMutation]);

    const handleUpload = useCallback(async (file: File) => {
        try {
            const res = await uploadCSVMutation.mutateAsync({ file, idempotencyKey: createIdempotencyKey() });
            message.success(res?.message || '批量导入成功');
        } catch {
            // handled by HTTP client
        }
        return false;
    }, [uploadCSVMutation]);

    const closeCreateModal = useCallback(() => {
        setCreateModalOpen(false);
    }, []);

    const closeEditModal = useCallback(() => {
        setEditModalOpen(false);
    }, []);

    return {
        users,
        loading: searchLoading,
        searchValue,
        setSearchValue,
        createModalOpen,
        setCreateModalOpen,
        editModalOpen,
        editingUser,
        handleSearch,
        handleCreate,
        handleEdit,
        handleUpdate,
        handleDeactivate,
        handleUpload,
        closeCreateModal,
        closeEditModal,
    };
}
